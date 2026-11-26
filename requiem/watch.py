"""WATCH: per-variant request and error counts for one flag, read from Prometheus.

The demo shop tags each span with flag.key / flag.variant; the OTel collector's spanmetrics
connector exports them as `traces_span_metrics_calls_total` with `flag_key`, `flag_variant`
and `status_code` labels (checked live, see SPIKE_RESULTS.md).
"""

from __future__ import annotations

import httpx

from requiem.decide import VariantWindow

CALLS = "traces_span_metrics_calls_total"


def window_queries(flag: str, window_seconds: int) -> tuple[str, str]:
    sel = f'{CALLS}{{flag_key="{flag}"}}'
    err = f'{CALLS}{{flag_key="{flag}",status_code="STATUS_CODE_ERROR"}}'
    return (
        f"sum by (flag_variant) (increase({sel}[{window_seconds}s]))",
        f"sum by (flag_variant) (increase({err}[{window_seconds}s]))",
    )


def parse_vector(body: dict) -> dict[str, float]:
    """Prometheus instant-vector response -> {flag_variant: value}."""
    if body.get("status") != "success":
        raise RuntimeError(f"prometheus query failed: {body.get('error', body)}")
    out: dict[str, float] = {}
    for r in body["data"]["result"]:
        variant = r["metric"].get("flag_variant", "")
        out[variant] = out.get(variant, 0.0) + float(r["value"][1])
    return out


def read_window(prom_url: str, flag: str, window_seconds: int, *, client: httpx.Client | None = None) -> dict[str, VariantWindow]:
    q_all, q_err = window_queries(flag, window_seconds)
    own = client is None
    c = client or httpx.Client(timeout=5.0)
    try:
        calls = parse_vector(c.get(f"{prom_url}/api/v1/query", params={"query": q_all}).json())
        errors = parse_vector(c.get(f"{prom_url}/api/v1/query", params={"query": q_err}).json())
    finally:
        if own:
            c.close()
    return {v: VariantWindow(requests=n, errors=errors.get(v, 0.0)) for v, n in calls.items()}
