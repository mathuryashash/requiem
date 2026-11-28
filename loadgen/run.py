"""Load generator with persistent identities, and the end-to-end kill measurement.

Each simulated shopper keeps one identity for the whole run, so Flagsmith keeps serving them
the same variant until Requiem changes it. This is load-generated traffic, not real users.

  python loadgen/run.py measure --trials 5   # needs the shop (port 8090) and requiem running

`measure` runs each trial like this: undo (experiment back to 50/50), wait for a clean window,
break the new checkout (fault on), then time two moments:
  t_kill  Requiem's incident file appears (it decided and called the Flagsmith API)
  t_safe  the first second after which no shopper is served the new checkout any more
Then fault off, and the next trial.

  python loadgen/run.py convert --shoppers 400 --prefix rt1_   # traffic for the buy_button RETIRE run

`convert` is how the buy_button experiment gets its evidence. Each shopper has a fixed identity,
views the product page once (that is the exposure; the shop reports which button they were
served), then buys or not. THE SCRIPT DECIDES WHO BUYS: green-button shoppers buy with
probability --rate-green (default 0.45), grey-button shoppers with --rate-control (default 0.20),
drawn from a random generator seeded by --seed and the identity. So the lift Flagsmith reports
afterwards measures this script's choices, not human behaviour. It proves the pipeline
(exposure, conversion, results, SRM, decision), not that green buttons sell more. Results go to fixtures/kill_e2e_<UTC time>_<n>trials.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SHOP = "http://127.0.0.1:8090"


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


def convert(shoppers: int, prefix: str, seed: int, rate_green: float, rate_control: float) -> None:
    import random

    served = {"green": 0, "control": 0}
    bought = {"green": 0, "control": 0}
    errors = 0
    with httpx.Client(timeout=15) as c:
        for i in range(shoppers):
            user = f"{prefix}{i:04d}"
            rng = random.Random(f"{seed}:{user}")
            try:
                v = c.get(f"{SHOP}/api/product", params={"user": user}).json()["variant"]
            except (httpx.HTTPError, KeyError, ValueError):
                errors += 1
                continue
            v = "green" if v == "green" else "control"
            served[v] += 1
            if rng.random() < (rate_green if v == "green" else rate_control):
                if c.post(f"{SHOP}/api/checkout", params={"user": user}).status_code == 200:
                    bought[v] += 1
    time.sleep(6)  # the shop's Flagsmith SDK flushes events every 2 s
    out = {"what": "script-generated shoppers for the buy_button experiment", "shoppers": shoppers, "prefix": prefix,
           "seed": seed, "purchase_probability_chosen_by_script": {"green": rate_green, "control": rate_control},
           "served": served, "purchases_sent": bought, "request_errors": errors,
           "note": "conversion rates were chosen by this script; lift measured downstream reflects them"}
    path = ROOT / "fixtures" / "retire" / f"loadgen_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{prefix.strip('_')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print("wrote", path.relative_to(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure")
    m.add_argument("--trials", type=int, default=5)
    r = sub.add_parser("run")
    r.add_argument("--seconds", type=float, default=60)
    cv = sub.add_parser("convert")
    cv.add_argument("--shoppers", type=int, default=400)
    cv.add_argument("--prefix", default="rt_")
    cv.add_argument("--seed", type=int, default=7)
    cv.add_argument("--rate-green", type=float, default=0.45)
    cv.add_argument("--rate-control", type=float, default=0.20)
    args = ap.parse_args()
    if args.cmd == "convert":
        convert(args.shoppers, args.prefix, args.seed, args.rate_green, args.rate_control)
    elif args.cmd == "measure":
        measure(args.trials)
    else:
        load = Load()
        pool = load.start()
        time.sleep(args.seconds)
        load.stop.set()
        pool.shutdown(wait=True)
        print(f"{len(load.log)} requests")


if __name__ == "__main__":
    main()
