"""Kill primitive, measured for real: experiment rollout -> 0%, then how long until the public
flags API serves the control value to an identity that was in the variant.

Runs 5 kill/restore cycles on the experiment created by spikes/experiment_e2e.py and writes
the raw timings to fixtures/spike1/16_kill_latency.json. Times are wall-clock from just before
the PATCH request to the first flags response that shows the new value (remote evaluation,
same machine, so this is the Flagsmith side only, not SDK polling or network).

Usage:  python spikes/kill_latency.py --token <admin API token>
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

BASE = "http://localhost:8000/api/v1"
OUT = Path(__file__).resolve().parent.parent / "fixtures" / "spike1"


def call(method, path, *, token=None, env_key=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    if env_key:
        headers["X-Environment-Key"] = env_key
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode()
        return r.status, (json.loads(txt) if txt else None)


def served_value(env_key: str, ident: str) -> str:
    _, body = call("GET", f"/identities/?identifier={ident}", env_key=env_key)
    flag = next(f for f in body["flags"] if f["feature"]["name"] == "buy_button")
    return str(flag["feature_state_value"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--trials", type=int, default=5)
    args = ap.parse_args()
    tok = args.token

    _, orgs = call("GET", "/organisations/", token=tok)
    org = next(o for o in orgs["results"] if o["name"] == "Requiem")
    _, projs = call("GET", f"/projects/?organisation={org['id']}", token=tok)
    proj = next(p for p in projs if p["name"] == "Demo Shop")
    _, envs = call("GET", f"/environments/?project={proj['id']}", token=tok)
    envs = envs.get("results", envs) if isinstance(envs, dict) else envs
    ek = next(e for e in envs if e["name"] == "Production")["api_key"]
    _, exps = call("GET", f"/environments/{ek}/experiments/", token=tok)
    exps = exps.get("results", exps) if isinstance(exps, dict) else exps
    exp = next(e for e in exps if e["name"] == "Green buy button")
    _, feats = call("GET", f"/projects/{proj['id']}/features/", token=tok)
    feats = feats.get("results", feats) if isinstance(feats, dict) else feats
    feature = next(f for f in feats if f["name"] == "buy_button")
    mv_id = feature["multivariate_options"][0]["id"]

    # An identity currently served the variant.
    ident = next(f"user_{i:03d}" for i in range(120) if served_value(ek, f"user_{i:03d}") == "green")

    def rollout(pct: float) -> None:
        call("PATCH", f"/environments/{ek}/experiments/{exp['id']}/rollout/", token=tok, body={
            "enabled": True,
            "rollout_percentage": pct,
            "feature_state_value": {"type": "string", "value": "grey"},
            "multivariate_feature_state_values": [
                {"multivariate_feature_option": mv_id, "percentage_allocation": 50},
            ],
        })

    def time_until(expected: str) -> tuple[float, int]:
        polls = 0
        t0 = time.perf_counter()
        while True:
            polls += 1
            if served_value(ek, ident) == expected:
                return (time.perf_counter() - t0) * 1000, polls
            if time.perf_counter() - t0 > 30:
                return float("nan"), polls
            time.sleep(0.02)

    trials = []
    for n in range(args.trials):
        t0 = time.perf_counter()
        rollout(0)
        patch_ms = (time.perf_counter() - t0) * 1000
        visible_ms, polls = time_until("grey")
        kill_total = patch_ms + visible_ms
        rollout(100)
        restore_ms, _ = time_until("green")
        trials.append({"trial": n + 1, "patch_ms": round(patch_ms, 1),
                       "until_control_served_ms": round(kill_total, 1), "polls": polls,
                       "restore_visible_ms": round(restore_ms, 1)})
        print(trials[-1])
        time.sleep(0.5)

    totals = sorted(t["until_control_served_ms"] for t in trials)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "16_kill_latency.json").write_text(json.dumps({
        "what": "rollout PATCH to 0% -> first flags API response serving control, same machine",
        "identity": ident,
        "trials": trials,
        "median_ms": totals[len(totals) // 2],
        "max_ms": totals[-1],
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
