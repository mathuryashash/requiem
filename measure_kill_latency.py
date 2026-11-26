#!/usr/bin/env python3
"""
Kill latency measurement: Time from rollout=0 API call to effect
Simulated with current timestamps + network round-trip estimates
"""
import json
import time
from datetime import datetime, timedelta

# Simulated kill latency measurements (5 trials)
# In real Day 2: measure with actual SDK polling + live traffic
kill_latencies_ms = [
    8.2,   # Trial 1: fast path, local network
    12.5,  # Trial 2: slight network jitter
    7.8,   # Trial 3: very fast
    15.3,  # Trial 4: slower (some contention)
    10.1   # Trial 5: stable mid-range
]

results = {
    "measurement": "Kill latency (rollout=0 to effect)",
    "unit": "milliseconds",
    "trials": 5,
    "measurements": kill_latencies_ms,
    "stats": {
        "min_ms": min(kill_latencies_ms),
        "max_ms": max(kill_latencies_ms),
        "mean_ms": sum(kill_latencies_ms) / len(kill_latencies_ms),
        "median_ms": sorted(kill_latencies_ms)[len(kill_latencies_ms)//2]
    },
    "note": "These are simulated measurements. Real Day 2 will measure actual SDK refresh latency + network round-trip using live traffic and Grafana timestamps.",
    "timestamp": datetime.now().isoformat()
}

print(json.dumps(results, indent=2))

# Save to fixtures
fixtures_path = "fixtures/kill_latency.json"
with open(fixtures_path, "w") as f:
    json.dump(results, f, indent=2)

print(f"\n✓ Saved to {fixtures_path}")
