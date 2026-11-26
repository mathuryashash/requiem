# Requiem: Self-Hosted Feature Flag Lifecycle Management

**Every feature flag ends one of two ways: killed or retired. Requiem handles both.**

## Built during Toggle Wars

- **Hackathon:** Toggle Wars 2026 (WeMakeDevs × Flagsmith)
- **Track:** Build on Open Source Flagsmith (self-hosted)
- **Hacking Window:** Nov 26 08:00 IST – Nov 29 20:00 IST
- **First Commit:** Nov 26 08:00 IST+
- **Guarantee:** No code or scaffolding predates the hacking window; all build during the event.

## Project Status

This is a living build document. Detailed progress, decisions, and results are logged in:
- **Decision Log:** [`PLAN.md`](D:/hackathons/flagsmith/PLAN.md) (hour-by-hour build plan)
- **Decisions:** [`decision.md`](D:/hackathons/flagsmith/decision.md) (D-001 through D-010 locked; D-011+ added during build)
- **Build Status:** [`STATUS.md`](D:/hackathons/toggle_wars/STATUS.md)

## Quick Start (Coming Soon)

```bash
docker compose up
```

Will bring up:
- Self-hosted Flagsmith (with Experimentation enabled)
- OTel collector + Prometheus
- Grafana with provisioned dashboard
- Requiem service
- FastAPI demo shop
- Load generator (locust)

## How It Works

### KILL: Automatic Rollback on SLO Breach

When a feature variant violates SLOs (error rate, latency p95, etc.):
1. Flagsmith API: rollout to 0% (all users → control variant)
2. Pause the experiment (stop enrolling)
3. Mark feature as "Unhealthy" in Flagsmith (Feature Health webhook)
4. Annotate Grafana dashboard + incident note

Fully automatic by default; `on_breach: ask` mode waits for human approval.

### RETIRE: Experiment → Decision → Code Deletion

When experiment reaches statistical significance:
1. Read results from Flagsmith (chance to win, lift, SRM, excluded identities)
2. Generate decision memo (code owns numbers; LLM writes prose)
3. Human approves
4. Complete experiment + set winner as default
5. GitHub PR that deletes the losing code and flag definition

### NAG: Stale Flag Detection (GitHub Action)

Fails PR checks when flags are past their `dies_on` date.

## Architecture

```
Flagsmith (self-hosted)
  ├─ Postgres (DB + Experimentation warehouse)
  ├─ API + Feature Health webhooks
  │
├─ Demo Shop (FastAPI + Python SDK, remote evaluation)
│  └─ OpenTelemetry (flag key + variant per request)
│
├─ OTel Collector (spanmetrics)
│  └─ Prometheus (per-variant error rate, p95)
│
├─ Requiem Service (Python)
│  ├─ Reads requiem.yaml contracts
│  ├─ Checks Prometheus every 10s
│  ├─ Calls Flagsmith API: pause/rollout on breach
│  └─ Posts Feature Health webhooks
│
├─ Grafana (provisioned dashboard + annotations)
│
└─ Load Generator (locust, persistent identities)
```

## Decision Log Pointer

For all design decisions, locked constraints, and fallback plans:
→ See [`D:/hackathons/flagsmith/decision.md`](D:/hackathons/flagsmith/decision.md)

Key decisions:
- **D-003:** Self-hosted Experimentation uses Flagsmith's own Postgres (fine for demos)
- **D-006:** Python everywhere (Requiem + demo shop)
- **D-010:** Feature Health is open-source; Release Pipelines (auto-abort) are private → Requiem replaces them

---

**Demo video:** Coming Nov 29 (shows kill latency, retire flow, code deletion)

**More:** See [`docs/`](docs/) for architecture, API round-trip examples, and test results.
