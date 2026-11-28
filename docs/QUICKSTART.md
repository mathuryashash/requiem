# Quickstart: one command

Needs Docker (Compose v2) and about 2 GB of free RAM for Docker. No Python, no `.env`, no tokens to copy.

```bash
git clone https://github.com/mathuryashash/requiem && cd requiem/deploy
docker compose up --detach --build
```

The first run builds two small images and pulls Flagsmith, Postgres, Prometheus, Grafana and the OpenTelemetry
collector, so allow a few minutes. Flagsmith's database migration is the slow step (about 1-2 minutes); a
one-shot `bootstrap` service waits for it, then creates the admin user, the organisation, project and
environment, the metric and the two running experiments (`new_checkout`, `buy_button`), and hands the keys
to the shop and to Requiem through a shared volume. Nothing to configure.

| What | Where |
|---|---|
| Flagsmith (log in with `admin@requiem.local` / `requiem-demo-password`, local demo only) | http://localhost:8000 |
| Demo shop | http://localhost:8090/health |
| Grafana (anonymous viewer, dashboard "Requiem") | http://localhost:3030 |
| Prometheus | http://localhost:9090 |

Check it is alive:

```bash
docker compose ps                 # bootstrap and migrate-db show "Exited (0)": they are one-shot by design
docker compose logs -f requiem    # one line per flag every 5 s: "new_checkout: not enough treatment traffic ..."
```

## See a kill

The traffic generator is opt-in (it is simulated shoppers, not real users):

```bash
docker compose --profile loadgen up --detach loadgen
# break the new checkout for the shoppers who are served it
curl -X POST localhost:8090/admin/fault -H 'content-type: application/json' -d '{"enabled":true,"rate":0.5}'
docker compose logs -f requiem    # three breached windows in a row, then: WARNING KILLED new_checkout
docker compose exec requiem ls incidents          # the incident note
```

In Flagsmith the "New checkout" experiment is now `paused` and the flag is marked unhealthy. To put it back:
`docker compose exec requiem python -m requiem.service undo new_checkout`.

Edit the contracts in `requiem.yaml` (thresholds, `on_breach: kill|ask`, `owner`, `dies_on`) and run
`docker compose restart requiem`.

## Change ports, run next to another stack

Every host port is an env var with today's default: `FLAGSMITH_PORT` (8000), `GRAFANA_PORT` (3030),
`PROMETHEUS_PORT` (9090), `SHOP_PORT` (8090), `OTLP_GRPC_PORT` (4317), `OTLP_HTTP_PORT` (4318). Use
`-p <name>` to keep a second copy apart, and `POSTGRES_CONTAINER_NAME` if you run two:

```bash
FLAGSMITH_PORT=8100 GRAFANA_PORT=3130 PROMETHEUS_PORT=9190 SHOP_PORT=8190 OTLP_GRPC_PORT=4417 \
OTLP_HTTP_PORT=4418 POSTGRES_CONTAINER_NAME=other_pg docker compose -p other up --detach --build
```

## Stop and clean up

```bash
docker compose --profile loadgen down -v    # -v also deletes the Flagsmith database and incident notes
```

Without `--profile loadgen`, `down` leaves a running load generator behind (profile services are skipped).

## NAG, the other half

`requiem.yaml` can give each flag an `owner:` and a `dies_on: YYYY-MM-DD`. `python -m requiem.nag` (or the
GitHub Action in `action.yml`) fails the build when a flag is past its date and lists every file and line that
still mentions it. The demo `new_checkout` is overdue on purpose, so the check fails on this repo.
