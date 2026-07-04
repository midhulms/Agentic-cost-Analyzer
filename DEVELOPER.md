# Developer Guide

Technical reference for anyone modifying, extending, or deploying this
codebase. If you just want to *use* the app, see `README.md` instead.

## Project layout

```
app/
  main.py         FastAPI app, all HTTP routes
  auth.py         Login, sessions, 5-free-use quota (stdlib hashlib, no bcrypt dep)
  router.py       route_request(): scoring -> agent pick -> model call -> log
  complexity.py   Prompt complexity scoring (structural signals, no LLM call)
  agents.py       The six agent personas + pick_agent() selection logic
  providers.py    call_model(): dispatches to OpenAI/Anthropic/mock
  cost_tracker.py SQLite schema, migrations, all read/write queries
  metrics.py      Prometheus counters/histograms, exposed at /metrics
  config.py       Settings (env-driven) + MODEL_CATALOG pricing table
  schemas.py      Pydantic request/response models
dashboard.py      Streamlit frontend
static/
  dashboard.html  Dependency-free HTML/JS frontend, served at /dashboard
tests/            pytest suite (router, complexity, metrics)
render.yaml       Render Blueprint (backend + HTML dashboard)
docker-compose.yml Local multi-service stack (API, Streamlit, Prometheus, Grafana)
monitoring/       Prometheus scrape configs
```

## Data model

Single SQLite database (`data/cost_router.db`, path set by
`Settings.db_path` in `app/config.py`), two tables:

- **`requests`** — one row per `/v1/route` call: route, model, agent, tokens,
  cost, latency, prompt preview, and (since the per-user fix below) a
  nullable `user_id` foreign key.
- **`users`** / **`sessions`** — created by `app/auth.py`: email + salted
  PBKDF2 password hash, `free_uses_remaining`, `is_paid`, and bearer tokens.

`cost_tracker.py` uses a manual, additive migration list (`_MIGRATIONS`) run
on every startup (`init_db()`), so upgrading an existing deployed DB in place
never loses historical rows — new columns are added with `ALTER TABLE ...
ADD COLUMN` guarded by a `PRAGMA table_info` check.

## Auth & per-user usage tracking

Every `/v1/route` call requires `Authorization: Bearer <token>` (returned by
`/v1/auth/signup` or `/v1/auth/login`). `app/auth.py`'s `require_user`
FastAPI dependency resolves that token to a user dict or raises 401.

**Global vs. personal endpoints** — this is the fix for "every user sees the
same usage": the original endpoints (`/v1/stats`, `/v1/recent`,
`/v1/stats/agents`, `/v1/stats/models`, `/v1/consumption/daily`,
`/v1/consumption/monthly`) are intentionally **global aggregates across every
account** — think of them as the public leaderboard. Each now has a sibling
`/me` endpoint (`/v1/stats/me`, `/v1/recent/me`, `/v1/stats/agents/me`,
`/v1/stats/models/me`, `/v1/consumption/daily/me`,
`/v1/consumption/monthly/me`) that requires login and filters every SQL
query by `WHERE user_id = ?`. Both dashboards default to the personal view
(a "My usage / Everyone" toggle switches back to global) — see
`dashboard.py`'s `view_choice` radio and `dashboard.html`'s `#scopeBar`.

Rows logged before this feature existed have `user_id = NULL` and are
counted only in the global endpoints, never attributed to any individual
account.

## Adding a new provider

1. Add pricing + metadata to `MODEL_CATALOG` in `app/config.py`.
2. Add the actual API call in `app/providers.py::call_model()` — follow the
   existing OpenAI/Anthropic branches; return `(text, input_tokens,
   output_tokens, token_count_method, is_exact)`.
3. No changes needed in `router.py` — it dispatches by model name via
   `api_for()`, already provider-agnostic.

## Testing

```bash
pip install -r requirements.txt
pytest tests/ -q
```
21 tests cover complexity scoring, routing decisions, and metrics — none of
them hit the HTTP layer directly, so adding auth did not require touching
existing tests. If you add new HTTP-level tests, remember `/v1/route` now
requires a valid bearer token (sign up via `/v1/auth/signup` in the test
fixture first).

## Real Stripe billing (currently mocked)

`POST /v1/auth/upgrade` in `app/main.py` currently just calls
`mark_paid(user_id)` directly — no payment is taken. To go live:

1. Replace the endpoint body with creating a Stripe Checkout Session and
   returning its URL instead of flipping `is_paid` immediately.
2. Add a `POST /v1/billing/webhook` endpoint that verifies Stripe's webhook
   signature and calls `mark_paid(user_id)` only on
   `checkout.session.completed`.
3. Store the Stripe customer ID on the `users` row (new column via the
   `_MIGRATIONS` pattern in `cost_tracker.py`) so refunds/cancellations can
   flip `is_paid` back off later.

## Deployment

### Backend + HTML dashboard → Render

`render.yaml` is a Blueprint — Render reads it automatically:

1. `dashboard.render.com` → **+ New → Blueprint** → connect your GitHub repo.
2. Render creates one service (`agentic-cost-router`) from the Dockerfile.
3. **Persistent storage — read this before relying on the data:** Render's
   free tier gives the container no persistent disk. Every redeploy and
   every cold-start after idling wipes `data/cost_router.db`. This is
   expected on free tier, not a bug. To fix permanently:
   - Upgrade to a paid instance and uncomment the `disk:` block in
     `render.yaml` (`mountPath: /app/data`), **or**
   - Point `db_path` at an external database (Render Postgres, Supabase,
     Turso) instead of local SQLite — more work, survives any plan tier.
4. Once "Live", your service exposes:
   - `/health` — plain liveness check
   - `/docs` — FastAPI's interactive Swagger UI
   - `/dashboard` — the HTML frontend
   - `/metrics` — Prometheus exposition format (see below)

### Streamlit dashboard → Streamlit Cloud

1. `share.streamlit.io` → New app → point at `dashboard.py`.
2. Settings → Secrets:
   ```toml
   ROUTER_API_BASE = "https://agentic-cost-router.onrender.com"
   ```
3. Save (auto-reboots). Confirm the sidebar shows your Render URL and login
   works.

### Prometheus + Grafana

The API already exposes Prometheus-format metrics with **zero extra setup**:
```bash
curl https://agentic-cost-router.onrender.com/metrics
```
Counters/histograms defined in `app/metrics.py`: request counts by
route/model/agent, token totals, cost totals (actual and baseline-frontier),
and latency.

**Option A — local, via Docker Compose** (`monitoring/prometheus.yml` is
already configured for the compose network):
```bash
docker compose up --build
```
- Prometheus UI: `http://localhost:9090`
- Grafana: `http://localhost:3000` (login `admin` / `admin`), add Prometheus
  as a data source pointing at `http://prometheus:9090`.

**Option B — online, via Grafana Cloud (free tier), scraping your live Render URL:**
1. Sign up at `grafana.com` → your Grafana Cloud stack → **Connections → Add
   new connection** → search **Prometheus**.
2. Choose the hosted/remote-write scrape option and set the scrape target to:
   ```
   https://agentic-cost-router.onrender.com/metrics
   ```
3. Set a scrape interval (15–30s is plenty for a demo app).
4. Once it's pulling data, **Dashboards → New → Add visualization**, select
   your Prometheus data source, and use queries like:
   ```promql
   sum(router_cost_usd_total)
   sum(rate(router_tokens_total[5m]))
   1 - (sum(router_cost_usd_total) / sum(router_baseline_cost_usd_total))
   ```
   (exact metric names are defined in `app/metrics.py` — check there if a
   query returns no series, names may differ slightly from the examples
   above depending on how you've customized `metrics.py`).

If you'd rather not stand up Grafana at all, `/metrics` is public and
`curl`-able on its own — sufficient to prove monitoring exists for a
portfolio/demo without extra infrastructure.

## Known limitations (by design, not bugs)

- **No "thinking" trace in Model Output.** Standard chat completion APIs
  don't expose a separate reasoning trace — only the final response, token
  counts, and cost, which is exactly what's shown. Surfacing genuine
  reasoning would require picking a model family that streams thinking
  tokens and handling that as a new response field end-to-end.
- **Free-tier data resets** — see the Render section above.
- **Upgrade is mocked** — see the Stripe section above.
