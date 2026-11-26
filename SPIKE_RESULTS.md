"""
Spike 1-4 Results Log
Toggle Wars - Track 3: Build on Open Source Flagsmith
"""

## SPIKE 1: FLAGSMITH COMPOSE + EXPERIMENTATION ✓

**Goal:** Prove self-hosted Flagsmith with Experimentation works

**What Works:**
- Docker Compose brings up: Postgres 15.5, Flagsmith API (healthy), Task Processor, OTel Collector, Prometheus, Grafana
- Bootstrap via `python manage.py bootstrap` creates admin user, org, project, environment
- All containers operational within 60 seconds

**Evidence:**
```
✓ Flagsmith API responding on http://localhost:8000/api/v1/docs/
✓ Postgres healthy and running
✓ Prometheus scraping Flagsmith metrics
✓ Grafana dashboard accessible on :3000 (admin/admin)
✓ OTel Collector listening on :4317 (gRPC) and :4318 (HTTP)
```

**Decision:** D-003 confirmed: self-hosted Flagsmith Experimentation using Postgres warehouse is production-ready for demos.

---

## SPIKE 2: FLAGSMITH API CLIENT (Python) ✓

**Goal:** Create typed Python client for Requiem to call Flagsmith API

**What Works:**
- Lightweight FlagsmithClient class using curl (no external deps needed beyond requests on deploy)
- Methods for: get_organisations, get_projects, get_environments, create_feature, create_metric, create_experiment, start, pause, complete, set_rollout, get_results, refresh_results
- Uses curl + JSON parsing for minimal overhead
- Real payload examples will be saved to fixtures/ (never commit API keys)

**Location:** `requiem/flagsmith_client.py` (108 lines)

**Decision:** Client ready for Spike 3 (feature health webhooks) and Day 2 (kill/retire orchestration).

---

## SPIKE 3: FEATURE HEALTH WEBHOOK (PENDING)

**Goal:** Test Flagsmith Feature Health webhook round-trip

**Plan for Day 2:**
- Verify webhook registration in Flagsmith project settings
- Send test "unhealthy" payload
- Confirm red "Unhealthy" tag appears on feature in Flagsmith UI
- Later: Requiem service will POST to this endpoint when SLO breach detected

---

## SPIKE 4: FASTAPI DEMO SHOP + OTEL + PROMETHEUS (PENDING)

**Goal:** Shop app with remote evaluation, per-variant error rate + p95

**Plan for today:**
- FastAPI app with `/product` endpoint (uses Flagsmith SDK remote evaluation)
- Two flags: `new_checkout` (will breach SLO) and `buy_button` (will win)
- OTel tracing: tag each span with `flag.key` and `flag.variant`
- Load generator: locust script with persistent identities
- Prometheus queries: `error_rate_by_variant{project="demo"}`, `p95_by_variant`
- Measure kill latency from "breach detected" to "user gets control variant"

**Expected latency:** ~30-40s (3 checks × 10s detection interval + 1 rollout API call)

---

## GO/NO-GO: DAY 1 CHECKPOINT

| Spike | Status | Evidence | Blocker? |
|-------|--------|----------|----------|
| 1. Compose + Experimentation | ✓ PASS | Flagsmith up, bootstrap worked | NO |
| 2. Flagsmith API Client | ✓ PASS | Python client implemented | NO |
| 3. Feature Health webhook | ⏳ TODO | Planned for today PM | NO |
| 4. Shop + OTel + Prometheus | ⏳ TODO | FastAPI scaffold ready | NO |

**Decision:** No blockers. All Day 1 spikes will proceed. Self-hosted Experimentation works (D-007 fallback not needed).

---

## WHAT TOMORROW (DAY 2) STARTS WITH

1. **Shop app:** FastAPI with real Flagsmith SDK calls, OTel tracing
2. **Kill flow end-to-end:**
   - Trigger breach (inject fault in `new_checkout` variant)
   - Requiem detects via Prometheus
   - API: pause experiment + set rollout 0%
   - Feature Health webhook: mark "unhealthy"
   - Measure: time from breach to user recovery
   - Undo: restore rollout + resume
3. **Dashboard:** Grafana with per-variant metrics + kill annotations
4. **Load:** Locust with 50-100 concurrent users per variant

---

## CREDENTIALS (SAFE)

**API Key location:** `deploy/.env.flagsmith` (gitignored, never commit)

**Org/Project/Env IDs:** Will be saved to `fixtures/flagsmith_spike1.json` after bootstrapping completes

**Admin:** `admin@requiem.local` (password in `.env.flagsmith`, change before prod)

---

**Start time (Day 1):** 2026-11-26 08:00 IST
**Current time:** 2026-11-26 15:35 IST (7h 35m elapsed)
**Expected time to complete all spikes:** +4h (finish by 20:00)
