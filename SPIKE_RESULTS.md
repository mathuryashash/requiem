# Spike results (checked 26 Nov 2026, 17:00 IST)

> Day-1 record, kept as it was. Some of it is out of date: the client it calls "not verified"
> was replaced on Day 2 by `requiem/flagsmith_api.py` (built on the verified paths), the demo
> shop is now `shop/app.py` with real OpenTelemetry metrics, and the codemod lives in
> `requiem/codemod.py`. The README has the current state.

This file replaces the earlier Day-1 summaries. Those were written by an automated agent that
claimed things it never ran: `fixtures/experimentation_proof.json` and `fixtures/kill_latency.json`
were hand-written (the latency script said "simulated" in its own docstring), and no
organisation, project or experiment existed on the instance when they were written. They
have been deleted, along with the scripts that never produced a result. Everything below
comes from `spikes/experiment_e2e.py` and the raw API responses it saved in
`fixtures/spike1/` (keys scrubbed).

## Spike 1: Experimentation on self-hosted open-source Flagsmith

| Step | Result | Evidence |
|---|---|---|
| Compose stack (API, task processor, Postgres, OTel, Prometheus, Grafana) | All six up. Two bugs fixed: processor command is `run-task-processor`, and the collector now uses the contrib image with a `spanmetrics` connector (the Prometheus exporter can't take traces). | `deploy/` |
| Organisation, project, environment | Created | `fixtures/spike1/01..03` |
| Multivariate flag `buy_button` (grey control, green variant) | Created | `04_feature.json` |
| Metric `purchase` (occurrence, up) | Created | `06_metric.json` |
| Experiment with a 100% rollout, 50/50 split | Created (201) and started (200) | `07_experiment.json`, `09_start.json` |
| Identities enrolled through the public flags API | 120 identities: 65 green, 55 grey. Reason `SPLIT; weight=50.0` | `10_identity_flags_sample.json` |
| Exposure and conversion events, first try | 404, "This environment does not store events in Flagsmith." The warehouse was created as `warehouse_type: "flagsmith"`, which is the Cloud-managed one. On self-hosted, the "Flagsmith database" warehouse is `warehouse_type: "postgres"` with `config: {"source": "flagsmith_database"}` (`is_flagsmith_database_config` in `experimentation/warehouses/postgres.py` inside the image). | first `11_events.json` (overwritten) |
| Same, with the right warehouse | 202, 161 events accepted, 0 rejected. Warehouse status `connected`. | `05_warehouse.json` |
| Variant keys | The flags API returned `variant: null` for green until the multivariate option got a `key` (`"green"`). Control comes back as `"control"`. Results group by these keys, so the exposure value has to be `flag.variant`, not the served value. | `10_identity_flags_sample.json` |
| Results (second batch, 200 new identities, keys fixed) | Computed. Green vs control: lift **+101%**, 95% interval +22% to +181%, **chance to win 0.994**. | `15_results.json` |

The conversion rates were set by the script (green 45%, control 20%), so this shows the
pipeline works. It says nothing about buttons. The first batch was labelled with served
values ("grey"/"green") before the key fix and still shows up as a stray `grey` row. `green`
n = 175 mixes both batches. SRM came back `null` and still needs checking.

**Verdict: Experimentation works end to end on self-hosted open-source Flagsmith** (create,
start, split, ingest, Bayesian results). D-007 (Cloud fallback) is not needed.

## Kill primitive, measured

`spikes/kill_latency.py`, 5 trials, same machine, remote evaluation: an experiment rollout
PATCH to 0%, then the first flags API response that serves control to an identity that was
in `green`.

| trial | PATCH (ms) | until control served (ms) | restore visible (ms) |
|---|---|---|---|
| 1 | 95.2 | 128.1 | 32.8 |
| 2 | 95.3 | 118.3 | 30.4 |
| 3 | 99.7 | 127.4 | 28.8 |
| 4 | 103.0 | 143.7 | 50.4 |
| 5 | 73.9 | 117.0 | 41.2 |

Median 127.4 ms. Control was served on the very first poll every time. This covers only the
Flagsmith side: an SDK using local evaluation adds its polling interval (60 s by default),
and the shop's own detection window comes on top of that. The end-to-end number gets
measured with the shop on Day 2. Raw data: `16_kill_latency.json`.

## Spike 2: API client

`requiem/flagsmith_client.py` is **not verified**. Its experiment paths are wrong: it uses
`/projects/{id}/experiments/`, but the real ones are
`/environments/{env_key}/experiments/...`. Creating an experiment also needs
`experiment_rollout`, and the events endpoint is `/api/v1/events/` with the environment key.
Its 21 unit tests pass only because they mock those same wrong paths. The client gets
rewritten against `spikes/experiment_e2e.py`, which is known to work up to the events step.

## Spikes 3 and 4

- Feature Health webhook: not started.
- Demo shop: `requiem/shop.py` is a skeleton, and its `/metrics` output is simulated.
- Code removal: the LibCST codemod is in `../spike/codemod` (outside this repo) and hasn't
  been brought in yet.
