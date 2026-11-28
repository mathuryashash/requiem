"""Demo shop: a small FastAPI app whose behaviour is driven by two Flagsmith experiments.

- `buy_button` (control grey, variant green) on GET /api/product
- `new_checkout` (control old, variant new) on POST /api/checkout. A fault switch makes the new
  checkout fail some of the time, which is what Requiem has to catch.

Flags are evaluated remotely with get_experiment_flag(), which also records the exposure.
Every request is one OpenTelemetry span tagged flag.key / flag.variant; the collector's
spanmetrics connector turns those into per-variant request and error counters in Prometheus.

Each experiment flag drives a real code branch (`if variant == ...`), which is what the RETIRE
codemod (requiem/codemod.py) deletes once the experiment is decided.

The traffic is load-generated (loadgen/run.py), not real users. The README says so.
"""

from __future__ import annotations

import logging
import os
import random
import threading

from fastapi import FastAPI, HTTPException
from flagsmith import Flagsmith
from flagsmith.analytics import EventProcessorConfig
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

FLAGSMITH_URL = os.getenv("FLAGSMITH_URL", "http://localhost:8000")
ENV_KEY = os.environ["FLAGSMITH_ENVIRONMENT_KEY"]
OTLP_URL = os.getenv("OTLP_TRACES_URL", "http://localhost:4318/v1/traces")

log = logging.getLogger("shop")

provider = TracerProvider(resource=Resource.create({"service.name": "demo-shop"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_URL), schedule_delay_millis=1000))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("demo-shop")

flagsmith = Flagsmith(
    environment_key=ENV_KEY,
    api_url=f"{FLAGSMITH_URL}/api/v1/",
    enable_events=True,
    # Self-hosted "Flagsmith database" warehouse: events go to the API itself.
    event_processor_config=EventProcessorConfig(events_api_url=f"{FLAGSMITH_URL}/api/", flush_interval_seconds=2.0),
)

app = FastAPI(title="Requiem demo shop")


class Fault(BaseModel):
    enabled: bool
    rate: float = Field(0.5, ge=0, le=1)


_fault = {"enabled": False, "rate": 0.5}
_fault_lock = threading.Lock()


def _variant(flag_key: str, user: str) -> tuple[str, str]:
    flag = flagsmith.get_experiment_flag(flag_key, identifier=user)
    variant = getattr(flag, "variant", None) or "control"
    return variant, str(flag.value)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/product")
def product(user: str) -> dict:
    with tracer.start_as_current_span("view_product") as span:
        variant, value = _variant("buy_button", user)
        span.set_attribute("flag.key", "buy_button")
        span.set_attribute("flag.variant", variant)
        span.set_attribute("http.route", "/api/product")
        if variant == "green":
            button = {"colour": "green", "label": "Buy now"}
        else:
            button = {"colour": "grey", "label": "Add to cart"}
        return {"user": user, "button_colour": button["colour"], "label": button["label"], "variant": variant}


@app.post("/api/checkout")
def checkout(user: str) -> dict:
    with tracer.start_as_current_span("checkout") as span:
        variant, value = _variant("new_checkout", user)
        span.set_attribute("flag.key", "new_checkout")
        span.set_attribute("flag.variant", variant)
        span.set_attribute("http.route", "/api/checkout")
        with _fault_lock:
            broken = _fault["enabled"] and variant != "control" and random.random() < _fault["rate"]
        if broken:
            span.set_status(Status(StatusCode.ERROR, "new checkout failed"))
            raise HTTPException(status_code=500, detail="checkout failed")
        flagsmith.track_event("purchase", identifier=user)
        if variant == "new":
            steps = ["cart", "pay"]  # the one-page checkout
        else:
            steps = ["cart", "address", "pay"]
        return {"user": user, "checkout": value, "variant": variant, "steps": steps, "ok": True}


@app.post("/admin/fault")
def set_fault(f: Fault) -> dict:
    """Break (or fix) the new checkout. Only the non-control variant is affected."""
    with _fault_lock:
        _fault.update(enabled=f.enabled, rate=f.rate)
        return dict(_fault)
