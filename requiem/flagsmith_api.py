"""Typed client for the Flagsmith admin API calls Requiem makes.

Every path here was checked against a live self-hosted Flagsmith (see SPIKE_RESULTS.md and
fixtures/spike1/). Experiment routes hang off the environment key, not the project.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class FlagsmithError(RuntimeError):
    """A Flagsmith API call failed; carries the status code and response body."""

    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        super().__init__(f"{method} {path} -> {status}: {body[:300]}")
        self.status = status
        self.body = body


@dataclass(frozen=True)
class Variant:
    option_id: int
    key: str
    value: str


@dataclass(frozen=True)
class Experiment:
    id: int
    name: str
    status: str
    feature_id: int
    feature_name: str = ""
    control_value: str | None = None
    variants: tuple[Variant, ...] = ()


class FlagsmithAPI:
    """Admin API for one environment. `token` is an admin user token (Authorization: Token ...)."""

    def __init__(
        self,
        base_url: str,
        token: str,
        environment_key: str,
        project_id: int,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.env = environment_key
        self.project_id = project_id
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1",
            headers={"Authorization": f"Token {token}"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, json: Any = None) -> Any:
        r = self._http.request(method, path, json=json)
        if r.status_code >= 400:
            raise FlagsmithError(method, path, r.status_code, r.text)
        return r.json() if r.content else None

    @staticmethod
    def _items(body: Any) -> list[dict]:
        return body.get("results", []) if isinstance(body, dict) else list(body or [])

    # ----- lookups -----
    def experiment_by_name(self, name: str) -> Experiment:
        for e in self._items(self._call("GET", f"/environments/{self.env}/experiments/")):
            if e["name"] == name:
                return self._experiment(e)
        raise LookupError(f"no experiment named {name!r} in this environment")

    @staticmethod
    def _experiment(e: dict) -> Experiment:
        f = e["feature"]
        if isinstance(f, dict):  # the list endpoint nests the feature, options included
            return Experiment(
                id=e["id"], name=e["name"], status=e["status"], feature_id=f["id"], feature_name=f["name"],
                control_value=str(f.get("initial_value")),
                variants=tuple(Variant(option_id=o["id"], key=o.get("key") or "", value=str(o.get("string_value")))
                               for o in f.get("multivariate_options", [])),
            )
        return Experiment(id=e["id"], name=e["name"], status=e["status"], feature_id=f)

    def variants(self, feature_id: int) -> list[Variant]:
        feature = self._call("GET", f"/projects/{self.project_id}/features/{feature_id}/")
        return [
            Variant(option_id=o["id"], key=o.get("key") or "", value=str(o.get("string_value")))
            for o in feature["multivariate_options"]
        ]

    def control_value(self, feature_id: int) -> str:
        feature = self._call("GET", f"/projects/{self.project_id}/features/{feature_id}/")
        return str(feature["initial_value"])

    # ----- experiment lifecycle -----
    def set_rollout(
        self,
        experiment_id: int,
        rollout_percentage: float,
        control_value: str,
        weights: dict[int, float],
    ) -> dict:
        """Enrol `rollout_percentage` % of identities; `weights` maps option id -> % of the enrolled.

        Rollout 0 sends everyone to the control value: that is Requiem's kill.
        """
        return self._call(
            "PATCH",
            f"/environments/{self.env}/experiments/{experiment_id}/rollout/",
            {
                "enabled": True,
                "rollout_percentage": rollout_percentage,
                "feature_state_value": {"type": "string", "value": control_value},
                "multivariate_feature_state_values": [
                    {"multivariate_feature_option": oid, "percentage_allocation": pct}
                    for oid, pct in weights.items()
                ],
            },
        )

    def pause(self, experiment_id: int) -> dict:
        """Stops the experiment collecting. Does NOT change what users are served (checked live)."""
        return self._call("POST", f"/environments/{self.env}/experiments/{experiment_id}/pause/")

    def start(self, experiment_id: int) -> dict:
        return self._call("POST", f"/environments/{self.env}/experiments/{experiment_id}/start/")

    def complete(self, experiment_id: int) -> dict:
        return self._call("POST", f"/environments/{self.env}/experiments/{experiment_id}/complete/")

    def results(self, experiment_id: int) -> dict | None:
        body = self._call("GET", f"/environments/{self.env}/experiments/{experiment_id}/results/")
        return (body or {}).get("results")

    def refresh_results(self, experiment_id: int) -> None:
        self._call("POST", f"/environments/{self.env}/experiments/{experiment_id}/results/refresh/")


def post_feature_health(
    webhook_url: str,
    feature: str,
    environment: str,
    *,
    unhealthy: bool,
    title: str = "",
    text: str = "",
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Mark a flag Unhealthy/Healthy through Flagsmith's Feature Health webhook provider."""
    body: dict[str, Any] = {
        "feature": feature,
        "environment": environment,
        "status": "unhealthy" if unhealthy else "healthy",
    }
    if text:
        body["reason"] = {"text_blocks": [{"title": title or "Requiem", "text": text}], "url_blocks": []}
    with httpx.Client(timeout=timeout, transport=transport) as c:
        r = c.post(webhook_url, json=body)
        if r.status_code >= 400:
            raise FlagsmithError("POST", "feature-health webhook", r.status_code, r.text)
