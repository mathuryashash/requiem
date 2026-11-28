# Requiem

**Every feature flag ends one of two ways: killed or retired. Requiem handles both, for self-hosted Flagsmith.**

Built for Toggle Wars (WeMakeDevs x Flagsmith), Track 3: Build on Open Source Flagsmith.
The hacking window was 26 Nov 08:00 IST to 29 Nov 20:00 IST. The first commit is from 26 Nov
14:50 IST, and nothing in this repo predates the window.

## What works (28 Nov)

| Piece | State | Evidence |
|---|---|---|
| Self-hosted Flagsmith with Experimentation (Postgres as the warehouse) | Works end to end: experiments split traffic, take events, and compute results | [SPIKE_RESULTS.md](SPIKE_RESULTS.md), `fixtures/spike1/` |
| Demo shop with two experiments (`buy_button`, `new_checkout`) and a fault switch | Works | `shop/app.py` |
| WATCH: OTel spans tagged `flag.key`/`flag.variant`, then collector spanmetrics, then per-variant counters in Prometheus | Works | `deploy/otel-collector-config.yml`, `requiem/watch.py` |
| KILL: contract in `requiem.yaml`, 3 breached windows in a row, then rollout to 0%, pause, Feature Health "Unhealthy", Grafana annotation, incident note | Works, measured below | `requiem/decide.py`, `requiem/service.py`, `incidents/` |
| Undo | Works | `python -m requiem.service undo new_checkout` |
| Grafana dashboard (per-variant error rate, requests, p95, kill annotations) | Provisioned | `deploy/grafana-provisioning/`, [screenshot](docs/grafana_kill.png) |
| RETIRE: read Flagsmith's results, decide WIN / LOSE / INCONCLUSIVE / SRM-BLOCK, write a decision memo, wait for approval | Works once, live (28 Nov): `buy_button` came back WIN, chance to win 0.9977, lift +71.5%, `srm_p_value` 0.1615. The conversions were script-generated (see below) | `requiem/retire.py`, `retirements/20261128T060639Z_buy_button.md`, `fixtures/retire/results_*.json` |
| RETIRE: approve, complete the experiment, serve the winner to everyone, delete the losing code on a local branch | Works once, live. Nothing was pushed and no PR was opened: opening it is a separate `--open-pr` step that has not been run | `fixtures/retire/approve_20261128T060742Z_buy_button.json`, branch `retire/buy_button-20261128T060742Z`, `retirements/*_PR.md` |
| LibCST codemod (`variant, value = _variant("flag", user)` plus `if variant == ...` chains, boolean `is_feature_enabled` ifs) | Works on the shop's patterns; refuses and lists anything else. Python only | `requiem/codemod.py`, `tests/test_codemod.py` |
| NAG: `owner` and `dies_on` per flag; fails the build past the date and lists every file:line that still uses the flag | Works locally (real run below). The GitHub Action wrapper (`action.yml`) has not run on GitHub yet | `requiem/nag.py`, `action.yml`, `.github/workflows/requiem-nag.yml`, `fixtures/nag/` |
| One-command quickstart: `docker compose up` brings up Flagsmith, the shop, Requiem and a bootstrap step that creates the experiments | Works on a fresh compose project (ports shifted, warm Docker cache) | [docs/QUICKSTART.md](docs/QUICKSTART.md), [docs/QUICKSTART_TEST.md](docs/QUICKSTART_TEST.md) |

## Retire it (28 Nov)

The other half of the lifecycle. `buy_button` is a green-vs-grey button experiment. The shop
asks Flagsmith which button a shopper gets (`variant, value = _variant("buy_button", user)`) and
branches on it. When the experiment has an answer, Requiem reads it, writes it up, waits for a
human, and then removes the flag from the code.

**What was run, and what it shows.** `python loadgen/run.py convert --shoppers 400` sent 400
shoppers with fixed identities through the shop. 186 were served green and 214 grey. **The
script decides who buys**: green shoppers buy with probability 0.45, grey with 0.20 (drawn
from a seeded random generator, `fixtures/retire/loadgen_*_rt1.json`). So the lift Flagsmith
reported (+71.5%, 95% interval +22% to +121%, chance to win 0.9977) comes from those numbers,
not from anyone liking a button. What it does show is that the whole path works against a
self-hosted Flagsmith: exposures, purchase events, Flagsmith's own results and `srm_p_value`
(0.1615: the split was fine), the decision, completing the experiment, and the code edit.

How the decision is made (`requiem/retire.py`; every threshold has a comment saying why, and
`docs/DECISIONS.md` D-013 lists them): Flagsmith does the statistics and Requiem only applies
rules to its numbers.

- **SRM-BLOCK** if Flagsmith's `srm_p_value` is under 0.001, or more than 5% of exposed identities
  saw two variants and were excluded. Checked first, because a broken split makes the rest meaningless.
- **INCONCLUSIVE** if any variant has fewer than 50 identities or 5 conversions (Flagsmith's own
  floors), or if the best variant's chance to win is between 0.05 and 0.95.
- **WIN** at chance to win >= 0.95, **LOSE** (keep control) at <= 0.05.
- Only WIN and LOSE can be approved.

```bash
# Needs: libcst (pip install libcst), the stack up, the shop running, a running experiment with data
python -m requiem.service retire buy_button        # refreshes results, writes retirements/<ts>_buy_button.{md,json}, changes nothing
python -m requiem.service approve buy_button --memo <first 8+ hex of the memo's sha256>
python -m requiem.service approve buy_button --memo <sha> --open-pr   # also pushes the branch and runs `gh pr create`
```

The memo is a template filled by code; no model writes any of it. Its `.json` is hashed
(sha256 of the exact file bytes, which `.gitattributes` keeps from being rewritten by line-ending
conversion), and `approve` only works on a file whose hash starts with what you typed.
`approve` then, in this order: makes a temporary git worktree on a new branch `retire/<flag>-<ts>`;
runs the codemod on the committed code and drops the flag's entry from `requiem.yaml`; compiles it
and runs the whole test suite there; commits; and only then calls Flagsmith
(`POST .../experiments/{id}/complete/` with `rollout_decision: variant`, which makes the winner the
environment default for everyone and removes the rollout override). If the codemod meets a pattern
it does not understand, or a test fails, it stops before touching Flagsmith. The branch for the live
run changes two files (`shop/app.py`: -8 +2 lines, `requiem.yaml`: the entry), and Flagsmith served
`green` to 12 of 12 checked identities afterwards (`served_after_complete` in the approve record).

Codemod limits, stated plainly: Python only; it understands `==`/`!=` against string literals on
the variant or value (with `elif`/`else`), and boolean `is_feature_enabled` ifs. It will not
touch a condition like `variant == "green" and user.vip`, a `match`, a one-line `if x: y`, a
re-assigned variable, or the flag key used any other way; those are listed in the report and block
the approval. After a retire, `_variant()` may be unused; it is not deleted.

**Reset to run it again:** `python demo/reset_demo.py buy_button` (deletes the experiment, even a
completed one, and creates and starts a fresh one; its results window starts from now). Then
`git restore shop/app.py requiem.yaml` if you had merged the retire branch, and delete old
`retire/*` branches. Before the first live run the demo's environment default split was 0%,
which is why Flagsmith returned `srm_p_value: null` in the Day-1 spike; `demo/setup_demo.py` now sets
it to 50/50 after starting an experiment (`reset_demo.py` runs it).

## Nag it (28 Nov)

A flag nobody decides on should not live forever. Each flag in `requiem.yaml` can carry an
`owner:` and a `dies_on: YYYY-MM-DD`. `python -m requiem.nag` reads them and:

- prints GitHub annotations: `::error` on the `dies_on` line and on each line of code that still
  mentions an overdue flag, `::warning` for flags due within 14 days (`--warn-days`);
- writes a table to the job summary when `$GITHUB_STEP_SUMMARY` is set;
- exits 1 if any flag is overdue or has a date it cannot read.

It scans only files git tracks (or would track), skips prose files unless `--include-docs`, and
with Flagsmith credentials in the environment it also says, using GET calls only, whether the
flag still exists and which experiment it is in. `--open-issue` would open one GitHub issue per
overdue flag through `gh`; it is off by default and has not been run against GitHub.

In this repo `new_checkout` is overdue on purpose (`dies_on: 2026-11-20`), so NAG fails here.
The real output of that run is in `fixtures/nag/` (exit code 1; 40 references for `new_checkout`,
including the shop, the Grafana dashboard, the load generator and the tests).

Other repos can use it as a step: `uses: mathuryashash/requiem@<tag>` with inputs `config`,
`warn-days`, `fail-on-overdue`, `scan-root` and `open-issue` (see `action.yml` and the example
workflow).

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

## Run it

One command, everything in Docker (details, ports and clean-up in [docs/QUICKSTART.md](docs/QUICKSTART.md)):

```bash
git clone https://github.com/mathuryashash/requiem && cd requiem/deploy
docker compose up --detach --build
docker compose --profile loadgen up --detach loadgen      # simulated shoppers, opt-in
curl -X POST localhost:8090/admin/fault -H 'content-type: application/json' -d '{"enabled":true,"rate":0.5}'
docker compose logs -f requiem                            # three breached windows, then KILLED new_checkout
```

Or run the shop and Requiem on the host (Python 3.12; this is how the measurements above were taken):

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

Grafana runs at http://localhost:3030 (dashboard "Requiem: per-variant health").

## Tests

`python -m pytest -q tests` (91 tests): NAG's date rules, reference scanning, annotation format,
exit codes and job summary; the retire rules (including SRM block, too few samples, hash
binding of the memo), the codemod's golden cases, idempotency and compile checks on the real shop,
and the breach rules (ceiling, minimum traffic, the control gap,
consecutive windows, bad contracts), the Flagsmith client against payload shapes recorded
from the live API, and the Prometheus parsing.

## Decisions

[docs/DECISIONS.md](docs/DECISIONS.md) is the decision log. That includes the corrected
entry where an automated agent claimed results that hadn't been measured.
