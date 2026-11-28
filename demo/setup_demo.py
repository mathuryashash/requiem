"""Create (or reuse) everything the demo needs on a fresh self-hosted Flagsmith.

Organisation "Requiem" > project "Demo Shop" > environment "Production", the Flagsmith-database
warehouse, a "purchase" metric, a Feature Health webhook provider, and two running
experiments with a 50/50 split:
  buy_button    control "grey", variant key "green"
  new_checkout  control "old",  variant key "new"

Prints the values Requiem and the shop need (environment key, project id, webhook URL) as
KEY=value lines for a .env file. Safe to run twice.

Usage:  python demo/setup_demo.py --token <admin API token> [--url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

FLAGS = [
    {"name": "buy_button", "control": "grey", "variant": "green",
     "experiment": "Green buy button", "hypothesis": "A green buy button raises purchases."},
    {"name": "new_checkout", "control": "old", "variant": "new",
     "experiment": "New checkout", "hypothesis": "The one-page checkout raises purchases."},
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--url", default="http://localhost:8000")
    args = ap.parse_args()
    base = args.url.rstrip("/") + "/api/v1"

    def call(method: str, path: str, body=None):
        req = urllib.request.Request(base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Token {args.token}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode()
                return json.loads(txt) if txt else None
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()[:500]}") from None

    def items(body):
        return body.get("results", []) if isinstance(body, dict) else list(body or [])

    def find(path, name):
        return next((x for x in items(call("GET", path)) if x.get("name") == name), None)

    org = find("/organisations/", "Requiem") or call("POST", "/organisations/", {"name": "Requiem"})
    proj = find(f"/projects/?organisation={org['id']}", "Demo Shop") or call(
        "POST", "/projects/", {"name": "Demo Shop", "organisation": org["id"]})
    env = find(f"/environments/?project={proj['id']}", "Production") or call(
        "POST", "/environments/", {"name": "Production", "project": proj["id"]})
    ek = env["api_key"]

    want = {"source": "flagsmith_database"}
    conns = items(call("GET", f"/environments/{ek}/warehouse-connections/"))
    for c in conns:
        if c.get("config") != want:
            call("DELETE", f"/environments/{ek}/warehouse-connections/{c['id']}/")
    if not any(c.get("config") == want for c in conns):
        call("POST", f"/environments/{ek}/warehouse-connections/", {"warehouse_type": "postgres", "config": want})

    metric = find(f"/environments/{ek}/experiment-metrics/", "purchase") or call(
        "POST", f"/environments/{ek}/experiment-metrics/",
        {"name": "purchase", "definition": {"version": 1, "event": "purchase"},
         "aggregation": "occurrence", "direction": "up"})

    providers = items(call("GET", f"/projects/{proj['id']}/feature-health/providers/"))
    hook = next((p for p in providers if p["name"] == "Webhook"), None) or call(
        "POST", f"/projects/{proj['id']}/feature-health/providers/", {"name": "Webhook"})

    for f in FLAGS:
        feat = find(f"/projects/{proj['id']}/features/", f["name"]) or call(
            "POST", f"/projects/{proj['id']}/features/",
            {"name": f["name"], "type": "MULTIVARIATE", "initial_value": f["control"], "default_enabled": True,
             "multivariate_options": [{"type": "unicode", "string_value": f["variant"], "key": f["variant"],
                                       "default_percentage_allocation": 50}]})
        opt = feat["multivariate_options"][0]
        if opt.get("key") != f["variant"]:
            # Without a key the flags API returns variant=null and results can't be grouped.
            call("PUT", f"/projects/{proj['id']}/features/{feat['id']}/mv-options/{opt['id']}/",
                 {"id": opt["id"], "feature": feat["id"], "type": "unicode", "string_value": f["variant"],
                  "default_percentage_allocation": 50, "key": f["variant"]})
        rollout = {"enabled": True, "rollout_percentage": 100,
                   "feature_state_value": {"type": "string", "value": f["control"]},
                   "multivariate_feature_state_values": [
                       {"multivariate_feature_option": opt["id"], "percentage_allocation": 50}]}
        existing = find(f"/environments/{ek}/experiments/", f["experiment"])
        if existing is None:
            # Flagsmith checks the split (srm_p_value) against the ENVIRONMENT DEFAULT, not the
            # experiment's rollout. A fresh option has 0% there, so results would carry srm_p_value
            # null forever. Match the default to the 50/50 the rollout uses. (Also resets a flag
            # that a completed experiment left serving one variant to everyone.)
            fs = next((x for x in items(call("GET", f"/environments/{ek}/featurestates/?feature={feat['id']}"))
                       if x.get("feature_segment") is None and x.get("identity") is None), None)
            if fs:
                call("PATCH", f"/environments/{ek}/featurestates/{fs['id']}/",
                     {"enabled": True, "feature_state_value": f["control"],
                      "multivariate_feature_state_values": [
                          {"multivariate_feature_option": opt["id"], "percentage_allocation": 50}]})
        exp = existing or call(
            "POST", f"/environments/{ek}/experiments/",
            {"feature": feat["id"], "name": f["experiment"], "hypothesis": f["hypothesis"],
             "metrics": [{"metric": metric["id"], "expected_direction": "increase"}],
             "experiment_rollout": rollout})
        if exp["status"] != "running":
            call("PATCH", f"/environments/{ek}/experiments/{exp['id']}/rollout/", rollout)
            call("POST", f"/environments/{ek}/experiments/{exp['id']}/start/")

    print(f"FLAGSMITH_ENVIRONMENT_KEY={ek}")
    print(f"FLAGSMITH_PROJECT_ID={proj['id']}")
    print(f"FLAGSMITH_HEALTH_WEBHOOK={hook['webhook_url']}")


if __name__ == "__main__":
    main()
