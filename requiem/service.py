"""Requiem service: WATCH each contracted flag, KILL it when the contract is breached.

  python -m requiem.service run              # loop forever (Ctrl+C to stop)
  python -m requiem.service undo new_checkout  # put the experiment back as it was

Settings come from requiem.yaml (contracts) and environment variables / .env:
FLAGSMITH_URL, FLAGSMITH_ADMIN_TOKEN, FLAGSMITH_ENVIRONMENT_KEY, FLAGSMITH_PROJECT_ID,
FLAGSMITH_HEALTH_WEBHOOK, PROMETHEUS_URL, optional GRAFANA_URL (+ GRAFANA_AUTH user:pass).

A kill = experiment rollout to 0% (everyone gets the control value), then pause (stops
collecting; pausing alone does not change what users see), then Feature Health "unhealthy"
on the flag inside Flagsmith, a Grafana annotation, and an incident note in incidents/.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

from requiem.decide import Contract, Tracker
from requiem.flagsmith_api import Experiment, FlagsmithAPI, post_feature_health
from requiem.watch import read_window

ROOT = Path(__file__).resolve().parent.parent
INCIDENTS = ROOT / "incidents"
log = logging.getLogger("requiem")


def load_env(path: Path = ROOT / ".env") -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def load_contracts(path: Path = ROOT / "requiem.yaml") -> tuple[list[Contract], float]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    # `owner` and `dies_on` belong to NAG (requiem/nag.py); the kill contract does not use them.
    contracts = [Contract(flag=name, **{k: v for k, v in spec.items() if k not in ("owner", "dies_on")})
                 for name, spec in (cfg.get("flags") or {}).items()]
    return contracts, float(cfg.get("check_every_seconds", 10))


def api_from_env() -> FlagsmithAPI:
    return FlagsmithAPI(
        os.environ.get("FLAGSMITH_URL", "http://localhost:8000"),
        os.environ["FLAGSMITH_ADMIN_TOKEN"],
        os.environ["FLAGSMITH_ENVIRONMENT_KEY"],
        int(os.environ["FLAGSMITH_PROJECT_ID"]),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def annotate_grafana(text: str, tags: list[str]) -> None:
    url = os.environ.get("GRAFANA_URL")
    if not url:
        return
    user, _, pw = os.environ.get("GRAFANA_AUTH", "admin:admin").partition(":")
    try:
        httpx.post(f"{url}/api/annotations", json={"text": text, "tags": tags}, auth=(user, pw), timeout=5)
    except httpx.HTTPError as e:  # an annotation is nice to have, never worth failing a kill
        log.warning("grafana annotation failed: %s", e)


def kill(api: FlagsmithAPI, c: Contract, tracker: Tracker) -> dict:
    exp = api.experiment_by_name(c.experiment)
    control = control_of(api, exp)
    weights = even_split(api, exp)
    t0 = time.time()
    api.set_rollout(exp.id, 0, control, weights)
    t_rollout = time.time()
    api.pause(exp.id)
    last = tracker.history[-1]
    reason = f"Killed by Requiem after {c.breach_windows} breached windows in a row. {last.reason}"
    hook = os.environ.get("FLAGSMITH_HEALTH_WEBHOOK")
    if hook:
        post_feature_health(hook, c.flag, os.environ.get("FLAGSMITH_ENVIRONMENT_NAME", "Production"),
                            unhealthy=True, title="Requiem kill", text=reason)
    annotate_grafana(f"Requiem killed {c.flag}: {last.reason}", ["requiem", "kill", c.flag])
    record = {"flag": c.flag, "experiment_id": exp.id, "at": _now(), "rollout_call_ms": round((t_rollout - t0) * 1000, 1),
              "weights_kept_for_undo": weights, "reason": reason,
              "windows": [v.reason for v in tracker.history[-c.breach_windows:]]}
    write_incident(record)
    return record


def write_incident(record: dict) -> Path:
    INCIDENTS.mkdir(exist_ok=True)
    stamp = record["at"].replace(":", "").replace("-", "")[:15]
    md = INCIDENTS / f"{stamp}_{record['flag']}.md"
    md.write_text(
        f"# Incident: `{record['flag']}` killed\n\n"
        f"- When (UTC): {record['at']}\n- Experiment id: {record['experiment_id']}\n"
        f"- What Requiem did: rollout to 0% (everyone back on control), paused the experiment, "
        f"marked the flag Unhealthy in Flagsmith.\n- Why: {record['reason']}\n\n"
        "## The windows that triggered it\n\n" + "".join(f"- {w}\n" for w in record["windows"]) +
        f"\n## Undo\n\n`python -m requiem.service undo {record['flag']}`\n",
        encoding="utf-8",
    )
    (INCIDENTS / f"{stamp}_{record['flag']}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return md


def even_split(api: FlagsmithAPI, exp: Experiment) -> dict[int, float]:
    """Equal shares for control and every variant (the demo's 50/50); the rest goes to control."""
    variants = exp.variants or tuple(api.variants(exp.feature_id))
    return {v.option_id: 100.0 / (len(variants) + 1) for v in variants}


def control_of(api: FlagsmithAPI, exp: Experiment) -> str:
    return exp.control_value if exp.control_value is not None else api.control_value(exp.feature_id)


def undo(api: FlagsmithAPI, c: Contract) -> None:
    exp = api.experiment_by_name(c.experiment)
    api.set_rollout(exp.id, 100, control_of(api, exp), even_split(api, exp))
    if exp.status != "running":  # start on a running experiment is a 400
        api.start(exp.id)
    hook = os.environ.get("FLAGSMITH_HEALTH_WEBHOOK")
    if hook:
        post_feature_health(hook, c.flag, os.environ.get("FLAGSMITH_ENVIRONMENT_NAME", "Production"), unhealthy=False)
    annotate_grafana(f"Requiem undo on {c.flag}", ["requiem", "undo", c.flag])


def run() -> None:
    contracts, every = load_contracts()
    api = api_from_env()
    prom = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    trackers = {c.flag: Tracker(c) for c in contracts}
    killed: set[str] = set()
    asked: set[str] = set()  # on_breach=ask: note written, waiting for a human (restart to re-arm)
    quiet_until: dict[str, float] = {}
    log.info("watching %s every %.0fs", ", ".join(trackers), every)
    with httpx.Client(timeout=5.0) as client:
        while True:
            for flag, tr in list(trackers.items()):
                if flag in asked:
                    continue
                if flag in killed:
                    # Re-arm after an undo, but only judge again once the window no longer
                    # holds requests from before the kill.
                    if api.experiment_by_name(tr.contract.experiment).status == "running":
                        killed.discard(flag)
                        trackers[flag] = tr = Tracker(tr.contract)
                        quiet_until[flag] = time.time() + tr.contract.window_seconds
                        log.info("%s: experiment running again, re-armed (quiet for %ss)", flag, tr.contract.window_seconds)
                    continue
                if time.time() < quiet_until.get(flag, 0):
                    continue
                try:
                    window = read_window(prom, flag, tr.contract.window_seconds, client=client)
                except (httpx.HTTPError, RuntimeError) as e:
                    log.warning("%s: no data this round (%s)", flag, e)
                    tr.streak = 0  # never kill on missing data
                    continue
                v = tr.observe(window)
                log.info("%s: %s (streak %d/%d)", flag, v.reason, tr.streak, tr.contract.breach_windows)
                if tr.should_act:
                    if tr.contract.on_breach == "kill":
                        rec = kill(api, tr.contract, tr)
                        log.warning("KILLED %s at %s", flag, rec["at"])
                    else:
                        write_incident({"flag": flag, "experiment_id": -1, "at": _now(),
                                        "reason": "on_breach=ask: waiting for a human. " + v.reason,
                                        "windows": [h.reason for h in tr.history[-tr.contract.breach_windows:]]})
                        log.warning("BREACH on %s, on_breach=ask: incident note written, no action", flag)
                        asked.add(flag)
                        continue
                    killed.add(flag)
            time.sleep(every)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    load_env()
    if len(argv) >= 1 and argv[0] == "run":
        run()
        return 0
    if len(argv) == 2 and argv[0] == "undo":
        contracts, _ = load_contracts()
        c = next(c for c in contracts if c.flag == argv[1])
        undo(api_from_env(), c)
        print(f"undone: {c.flag} back to a 100% rollout, experiment running, flag healthy")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
