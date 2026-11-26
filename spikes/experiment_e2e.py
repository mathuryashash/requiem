"""Spike 1, run for real: does Experimentation work on self-hosted, open-source Flagsmith?

Creates org -> project -> environment -> multivariate flag -> Flagsmith-database warehouse ->
metric -> experiment, starts it, enrols identities through the public flags API, sends
exposure and conversion events to /api/v1/events/, then asks for results.

Every API response is written to fixtures/spike1/<step>.json (keys and tokens scrubbed),
so the claim can be checked without re-running anything.

Usage:  python spikes/experiment_e2e.py --token <admin API token> [--n 60]
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8000/api/v1"
OUT = Path(__file__).resolve().parent.parent / "fixtures" / "spike1"
SECRET_KEYS = {"api_key", "key", "token", "client_api_key", "credentials"}


def scrub(obj):
    if isinstance(obj, dict):
        return {k: ("<scrubbed>" if k in SECRET_KEYS and v else scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(x) for x in obj]
    if isinstance(obj, str):
        return re.sub(r"\b[A-Za-z0-9]{20,}\b", "<scrubbed>", obj)
    return obj


def save(step: str, status: int, body) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{step}.json").write_text(
        json.dumps({"status": status, "body": scrub(body)}, indent=2), encoding="utf-8"
    )


def call(method: str, path: str, *, token=None, env_key=None, body=None, step=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    if env_key:
        headers["X-Environment-Key"] = env_key
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode()
            status, parsed = r.status, (json.loads(txt) if txt else None)
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            parsed = json.loads(txt)
        except ValueError:
            parsed = txt[:2000]
        status = e.code
    if step:
        save(step, status, parsed)
    print(f"{method:5} {path[:70]:70} -> {status}")
    return status, parsed


def must(result, ok=(200, 201, 202, 204)):
    status, body = result
    if status not in ok:
        raise SystemExit(f"FAILED with {status}: {json.dumps(body)[:800]}")
    return body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--n", type=int, default=60, help="identities to enrol")
    args = ap.parse_args()
    tok = args.token
    random.seed(7)

    def find(path, name, key="name"):
        status, body = call("GET", path, token=tok)
        items = body.get("results", body) if isinstance(body, dict) else body
        return next((x for x in items or [] if x.get(key) == name), None)

    org = find("/organisations/", "Requiem") or must(
        call("POST", "/organisations/", token=tok, body={"name": "Requiem"}, step="01_org"))
    proj = find(f"/projects/?organisation={org['id']}", "Demo Shop") or must(
        call("POST", "/projects/", token=tok, body={"name": "Demo Shop", "organisation": org["id"]},
             step="02_project"))
    env = find(f"/environments/?project={proj['id']}", "Production") or must(
        call("POST", "/environments/", token=tok, body={"name": "Production", "project": proj["id"]},
             step="03_environment"))
    ek = env["api_key"]

    feature = find(f"/projects/{proj['id']}/features/", "buy_button") or must(
        call("POST", f"/projects/{proj['id']}/features/", token=tok, step="04_feature", body={
            "name": "buy_button",
            "type": "MULTIVARIATE",
            "initial_value": "grey",
            "default_enabled": True,
            "multivariate_options": [
                {"type": "unicode", "string_value": "green", "default_percentage_allocation": 50},
            ],
        }))

    # Self-hosted "Flagsmith database" warehouse = type postgres + this exact config
    # (experimentation/warehouses/postgres.py: is_flagsmith_database_config).
    # warehouse_type "flagsmith" is the Cloud-managed warehouse and won't accept SDK events here.
    want = {"source": "flagsmith_database"}
    status, conns = call("GET", f"/environments/{ek}/warehouse-connections/", token=tok)
    conns = conns.get("results", conns) if isinstance(conns, dict) else conns
    for c in conns or []:
        if c.get("config") != want:
            call("DELETE", f"/environments/{ek}/warehouse-connections/{c['id']}/", token=tok,
                 step="05a_wrong_warehouse_deleted")
            conns = []
    if not conns:
        must(call("POST", f"/environments/{ek}/warehouse-connections/", token=tok,
                  body={"warehouse_type": "postgres", "config": want}, step="05_warehouse"))
    metric = find(f"/environments/{ek}/experiment-metrics/", "purchase") or must(
        call("POST", f"/environments/{ek}/experiment-metrics/", token=tok, step="06_metric",
             body={"name": "purchase", "definition": {"version": 1, "event": "purchase"},
                   "aggregation": "occurrence", "direction": "up"}))

    # Rollout: everyone enrolled, 50/50 between control (grey) and green.
    mv_id = feature["multivariate_options"][0]["id"]
    rollout = {
        "enabled": True,
        "rollout_percentage": 100,
        "feature_state_value": {"type": "string", "value": "grey"},
        "multivariate_feature_state_values": [
            {"multivariate_feature_option": mv_id, "percentage_allocation": 50},
        ],
    }
    exp = find(f"/environments/{ek}/experiments/", "Green buy button") or must(
        call("POST", f"/environments/{ek}/experiments/", token=tok, step="07_experiment", body={
        "feature": feature["id"],
        "name": "Green buy button",
        "hypothesis": "A green buy button raises purchases.",
        "metrics": [{"metric": metric["id"], "expected_direction": "increase"}],
        "experiment_rollout": rollout,
    }))
    eid = exp["id"]
    if exp.get("status") != "running":
        must(call("POST", f"/environments/{ek}/experiments/{eid}/start/", token=tok, step="09_start"))

    # Enrol identities through the public flags API, like an SDK would.
    variants: dict[str, str] = {}
    first = None
    for i in range(args.n):
        ident = f"user_{i:03d}"
        status, body = call("GET", f"/identities/?identifier={ident}", env_key=ek)
        if first is None:
            first = body
            save("10_identity_flags_sample", status, body)
        flag = next((f for f in body.get("flags", []) if f["feature"]["name"] == "buy_button"), None)
        variants[ident] = str(flag.get("feature_state_value")) if flag else "missing"
    counts: dict[str, int] = {}
    for v in variants.values():
        counts[v] = counts.get(v, 0) + 1
    print("variant split:", counts)

    # Exposure + conversion events. Green converts more often, so a winner should emerge.
    now_ms = int(time.time() * 1000)
    events = []
    for ident, v in variants.items():
        events.append({"event": "$flag_exposure", "feature_name": "buy_button", "identifier": ident,
                       "value": v, "timestamp": now_ms, "metadata": {"experiment_id": eid}})
        p = 0.45 if v == "green" else 0.2
        if random.random() < p:
            events.append({"event": "purchase", "identifier": ident, "timestamp": now_ms + 1000})
    must(call("POST", "/events/", env_key=ek, body={"events": events}, step="11_events"))

    time.sleep(3)
    call("POST", f"/environments/{ek}/experiments/{eid}/exposures/refresh/", token=tok, step="12_exposures_refresh")
    call("POST", f"/environments/{ek}/experiments/{eid}/results/refresh/", token=tok, step="13_results_refresh")
    for attempt in range(12):
        time.sleep(5)
        s1, exposures = call("GET", f"/environments/{ek}/experiments/{eid}/exposures/", token=tok)
        s2, results = call("GET", f"/environments/{ek}/experiments/{eid}/results/", token=tok)
        if results and s2 == 200 and (not isinstance(results, dict) or results.get("status") != "computing"):
            break
    save("14_exposures", s1, exposures)
    save("15_results", s2, results)
    (OUT / "ids.json").write_text(json.dumps({"organisation": org["id"], "project": proj["id"],
                                              "environment": env["id"], "feature": feature["id"],
                                              "metric": metric["id"], "experiment": eid,
                                              "variant_split": counts}, indent=2), encoding="utf-8")
    print("done; fixtures in", OUT)


if __name__ == "__main__":
    main()
