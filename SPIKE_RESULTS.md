# Spike results (checked 26 Nov 2026, 16:50 IST)

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
| Exposure and conversion events to `POST /api/v1/events/` | **404: "This environment does not store events in Flagsmith."** | `11_events.json` |
| Results | Not reached yet | n/a |

Why the events failed: the warehouse was created as `warehouse_type: "flagsmith"`, which is
the Cloud-managed warehouse. On self-hosted, the "Flagsmith database" warehouse is
`warehouse_type: "postgres"` with `config: {"source": "flagsmith_database"}` (see
`is_flagsmith_database_config` in `experimentation/warehouses/postgres.py` inside the image).
`spikes/experiment_e2e.py` now deletes the wrong connection and creates the right one, but it
has not been re-run yet.

**Verdict so far: experiments can be created, started and split traffic on self-hosted.
Event ingestion and results are NOT proven yet.** D-007 (Cloud fallback) stays open until
the re-run either shows results or fails for a reason we can't fix.

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
- Kill latency: not measured. There is no real number yet.
- Code removal: the LibCST codemod is in `../spike/codemod` (outside this repo) and hasn't
  been brought in yet.
