# Requiem

**Every feature flag ends one of two ways: killed or retired. Requiem handles both, for self-hosted Flagsmith.**

Built for Toggle Wars (WeMakeDevs x Flagsmith), Track 3: Build on Open Source Flagsmith.
The hacking window was 26 Nov 08:00 IST to 29 Nov 20:00 IST. The first commit is from 26 Nov
14:50 IST, and nothing in this repo predates the window.

## What works today (26 Nov)

| Piece | State | Evidence |
|---|---|---|
| Self-hosted Flagsmith with Experimentation (Postgres as the warehouse) | Works end to end: experiments split traffic, take events, and compute results | [SPIKE_RESULTS.md](SPIKE_RESULTS.md), `fixtures/spike1/` |
| Demo shop with two experiments (`buy_button`, `new_checkout`) and a fault switch | Works | `shop/app.py` |
| WATCH: OTel spans tagged `flag.key`/`flag.variant`, then collector spanmetrics, then per-variant counters in Prometheus | Works | `deploy/otel-collector-config.yml`, `requiem/watch.py` |
| KILL: contract in `requiem.yaml`, 3 breached windows in a row, then rollout to 0%, pause, Feature Health "Unhealthy", Grafana annotation, incident note | Works, measured below | `requiem/decide.py`, `requiem/service.py`, `incidents/` |
| Undo | Works | `python -m requiem.service undo new_checkout` |
| Grafana dashboard (per-variant error rate, requests, p95, kill annotations) | Provisioned | `deploy/grafana-provisioning/`, [screenshot](docs/grafana_kill.png) |
| RETIRE (results, decision memo, approval, PR that deletes the losing code) | Not built yet (Day 3) | the LibCST codemod is prototyped outside this repo |
| NAG GitHub Action (`dies_on`) | Not built yet (Day 3) | n/a |

## Measured: how fast a broken variant gets killed

`loadgen/run.py measure` runs 30 shoppers with fixed identities against the shop. It turns on
the fault (the new checkout then fails 50% of the time; control is never affected) and times
two things: when Requiem's kill lands, and when the last shopper is served the new checkout.
Each trial starts from a clean 50/50 split. With the contract in `requiem.yaml` (5% ceiling,
30 s windows, checked every 5 s, 3 breaches in a row):

| trial | fault on to kill (s) | fault on to last "new" checkout served (s) | rollout API call (ms) |
|---|---|---|---|
| 1 | 24.0 | 23.6 | 176 |
| 2 | 24.7 | 24.1 | 234 |
| 3 | 20.7 | 20.2 | 144 |
| 4 | 24.5 | 24.0 | 158 |
| 5 | 24.8 | 24.3 | 284 |

Median 24.5 s from breakage to kill (20.7 to 24.8 s). In every trial the last new checkout was served
0.34-0.63 s before Requiem's incident note appeared, which is while the kill sequence was still running
(rollout first, then pause, Feature Health and notes). No shopper got the new checkout after that. Raw data: `fixtures/kill_e2e_20261126T121218Z_5trials.json`.

Where the time goes, roughly: up to about 10 s for spans to become a Prometheus sample
(collector flush every 5 s, scrape every 5 s), the first breached check, then two more checks
5 s apart. Once Requiem calls Flagsmith, the switch itself is immediate: the rollout call takes 144-284 ms.

This is load-generated traffic on one laptop, not real users.

## How Flagsmith is used

- **Experiments (open source, beta):** `get_experiment_flag()` in the shop (remote
  evaluation), and exposure plus `purchase` events sent to the self-hosted API. Results come
  from `/experiments/{id}/results/`.
- **Kill:** `PATCH /environments/{key}/experiments/{id}/rollout/` with `rollout_percentage: 0`
  sends everyone to the control value. `POST .../pause/` stops collection. Pausing alone does
  **not** change what users are served (checked live), which is why Requiem does both.
- **Feature Health (open source):** Requiem posts to the Webhook provider, so the flag shows
  as Unhealthy inside Flagsmith with the reason. Undo posts healthy.
- Gotchas found on the way, also in SPIKE_RESULTS.md:
  - On self-hosted, the "Flagsmith database" warehouse is `warehouse_type: postgres` with
    `config: {"source": "flagsmith_database"}`.
  - Multivariate options need a `key`, otherwise the flags API returns `variant: null`.
  - The experiment list nests the whole feature.

## Run it (local, Windows or Linux)

```bash
# 1. Flagsmith, Postgres, task processor, OTel collector, Prometheus, Grafana
cd deploy && docker compose up -d && cd ..
# 2. Create an admin user + token, then the org/project/experiments (prints the .env values)
python demo/setup_demo.py --token <admin token>   # writes nothing; put the output in .env
# .env also needs FLAGSMITH_ADMIN_TOKEN, FLAGSMITH_URL, PROMETHEUS_URL, GRAFANA_URL
# 3. Shop and Requiem
python -m uvicorn shop.app:app --port 8090 --env-file .env
python -m requiem.service run
# 4. Break it and watch it get killed
python loadgen/run.py measure --trials 1
```

Grafana runs at http://localhost:3030 (dashboard "Requiem: per-variant health"). The
one-command `docker compose up` with the shop and Requiem inside it is still to do (Day 3).

## Tests

`python -m pytest -q tests`: the breach rules (ceiling, minimum traffic, the control gap,
consecutive windows, bad contracts), the Flagsmith client against payload shapes recorded
from the live API, and the Prometheus parsing.

## Decisions

[docs/DECISIONS.md](docs/DECISIONS.md) is the decision log. That includes the corrected
entry where an automated agent claimed results that hadn't been measured.
