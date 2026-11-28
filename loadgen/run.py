"""Load generator with persistent identities, and the end-to-end kill measurement.

Each simulated shopper keeps one identity for the whole run, so Flagsmith keeps serving them
the same variant until Requiem changes it. This is load-generated traffic, not real users.

  python loadgen/run.py measure --trials 5   # needs the shop (port 8090) and requiem running

`measure` runs each trial like this: undo (experiment back to 50/50), wait for a clean window,
break the new checkout (fault on), then time two moments:
  t_kill  Requiem's incident file appears (it decided and called the Flagsmith API)
  t_safe  the first second after which no shopper is served the new checkout any more
Then fault off, and the next trial. Results go to fixtures/kill_e2e_<UTC time>_<n>trials.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SHOP = os.getenv("SHOP_URL", "http://127.0.0.1:8090")


class Load:
    """Shoppers hitting /api/checkout in a loop; remembers what each one was served last."""

    def __init__(self, n: int = 30, prefix: str = "lg_", pause_s: float = 0.3) -> None:
        self.ids = [f"{prefix}{i:03d}" for i in range(n)]
        self.pause_s = pause_s
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.log: list[tuple[float, str, str, int]] = []  # (time, user, variant, status)

    def _shopper(self, user: str) -> None:
        with httpx.Client(timeout=10) as c:
            while not self.stop.is_set():
                t = time.time()
                try:
                    r = c.post(f"{SHOP}/api/checkout", params={"user": user})
                    variant = r.json().get("variant", "?") if r.status_code == 200 else "?"
                    # A 500 only comes from the new checkout (the fault hits nothing else).
                    if r.status_code == 500:
                        variant = "new"
                    with self.lock:
                        self.log.append((t, user, variant, r.status_code))
                except httpx.HTTPError:
                    pass
                time.sleep(self.pause_s)

    def start(self) -> ThreadPoolExecutor:
        pool = ThreadPoolExecutor(max_workers=len(self.ids))
        for u in self.ids:
            pool.submit(self._shopper, u)
        return pool

    def last_new_after(self, t0: float) -> float | None:
        with self.lock:
            news = [t for t, _, v, _ in self.log if t >= t0 and v == "new"]
        return max(news) if news else None


def fault(on: bool, rate: float = 0.5) -> None:
    httpx.post(f"{SHOP}/admin/fault", json={"enabled": on, "rate": rate}, timeout=5).raise_for_status()


def undo(flag: str) -> None:
    subprocess.run([sys.executable, "-m", "requiem.service", "undo", flag], cwd=ROOT, check=True,
                   capture_output=True)


def measure(trials: int, flag: str = "new_checkout") -> None:
    load = Load()
    pool = load.start()
    incidents = ROOT / "incidents"
    results = []
    try:
        for n in range(1, trials + 1):
            fault(False)
            undo(flag)
            time.sleep(45)  # requiem re-arms after a 30 s quiet window; let a clean window build
            before = set(incidents.glob(f"*_{flag}.json")) if incidents.exists() else set()
            t_fault = time.time()
            fault(True)
            t_kill = None
            while time.time() - t_fault < 180:
                new = set(incidents.glob(f"*_{flag}.json")) - before
                if new:
                    t_kill = time.time()
                    rec = json.loads(sorted(new)[-1].read_text(encoding="utf-8"))
                    break
                time.sleep(0.2)
            if t_kill is None:
                results.append({"trial": n, "error": "no kill within 180 s"})
                continue
            time.sleep(10)  # watch long enough to see the variant stop being served
            last_new = load.last_new_after(t_fault)
            results.append({
                "trial": n,
                "fault_to_kill_s": round(t_kill - t_fault, 1),
                "fault_to_last_new_checkout_served_s": round(last_new - t_fault, 1) if last_new else None,
                "kill_to_last_new_checkout_served_s": round(last_new - t_kill, 2) if last_new else None,
                "rollout_call_ms": rec.get("rollout_call_ms"),
                "reason": rec.get("reason"),
            })
            print(results[-1], flush=True)
    finally:
        fault(False)
        load.stop.set()
        pool.shutdown(wait=True)
    ok = [r for r in results if "fault_to_kill_s" in r]
    out = {"what": "fault switched on -> Requiem kill (incident file) -> last 'new' checkout served",
           "shoppers": len(load.ids), "request_pause_s": load.pause_s,
           "contract": "requiem.yaml new_checkout", "trials": results,
           "median_fault_to_kill_s": sorted(r["fault_to_kill_s"] for r in ok)[len(ok) // 2] if ok else None}
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = ROOT / "fixtures" / f"kill_e2e_{stamp}_{len(results)}trials.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("wrote", path.relative_to(ROOT), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure")
    m.add_argument("--trials", type=int, default=5)
    r = sub.add_parser("run")
    r.add_argument("--seconds", type=float, default=60)
    args = ap.parse_args()
    if args.cmd == "measure":
        measure(args.trials)
    else:
        load = Load()
        pool = load.start()
        time.sleep(args.seconds if args.seconds > 0 else 10**9)  # 0 = run until stopped
        load.stop.set()
        pool.shutdown(wait=True)
        print(f"{len(load.log)} requests")


if __name__ == "__main__":
    main()
