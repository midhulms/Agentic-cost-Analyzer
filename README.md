# Agentic Cost Router

**Every prompt, routed to an agent, priced to the token.**

A small, fully-working system that sits in front of an LLM call and decides, per
prompt, whether it actually needs a frontier model — or whether a cheaper model
would do the same job for a fraction of the cost. Every decision, token count,
and dollar amount is logged and shown back to you, not just estimated.

**Live demo:** `https://agentic-cost-router.onrender.com/dashboard`
**API docs:** `https://agentic-cost-router.onrender.com/docs`

> Free tier note: the demo above resets its usage data whenever the service
> redeploys or wakes up from being idle — that's a hosting limitation, not a
> bug. See [Deployment](#deployment) below.

---

## What it actually does

1. **Scores prompt complexity** (0.0–1.0) using structural signals — length,
   reasoning/planning keywords, code fences, multi-step language — no LLM
   call needed just to make this decision.
2. **Routes** the prompt to a cheap tier or a frontier tier based on that
   score, and attributes it to one of six named agent personas (Compiler,
   Atlas, Prism, Voyager, Sparrow, Echo) chosen by what the prompt looks like
   it needs.
3. **Calls the model for real** — plug in your own OpenAI or Anthropic API
   key and it dispatches a genuine API call, not a canned response. No key?
   It returns a clearly-labeled mock reply instead, so the whole flow still
   works with zero setup.
4. **Counts tokens exactly** — via `tiktoken` when available, provider-reported
   usage when the API returns it, or a documented approximation as a last
   resort. It tells you which method was used for every single response.
5. **Prices every request** against a small model-pricing catalog and shows
   input cost, output cost, and — for cheap-routed requests — what the same
   prompt would have cost on the frontier tier instead, so "money saved" is a
   real number, not a marketing one.
6. **Accounts require login**, with 5 free requests per account before a
   (currently mock) upgrade is required — see [Billing](#billing--upgrades).
7. **Two dashboards, one backend**: a dependency-free HTML page served
   directly by the API (`/dashboard`) and a separate Streamlit app
   (`dashboard.py`) — both read/write the same data through the same REST API.
8. **Per-account usage tracking**: each logged-in user sees their own request
   count, tokens, and spend by default, with a one-click toggle to view the
   combined "everyone" total instead.

---

## Architecture

```
                     ┌─────────────────────┐
                     │   FastAPI backend    │
  HTML dashboard ───▶│   app/main.py        │◀─── Streamlit dashboard
  (static/           │                       │     (dashboard.py)
   dashboard.html)   │  ├─ auth.py  (login,  │
                      │  │   sessions, quota) │
                      │  ├─ router.py (route  │
                      │  │   + dispatch)      │
                      │  ├─ complexity.py     │
                      │  ├─ providers.py      │
                      │  │   (OpenAI/         │
                      │  │    Anthropic call) │
                      │  ├─ cost_tracker.py   │
                      │  │   (SQLite log)     │
                      │  └─ metrics.py        │
                      │      (Prometheus)     │
                      └──────────┬────────────┘
                                 │
                        SQLite (data/cost_router.db)
                                 │
                         GET /metrics ──▶ Prometheus / Grafana
```

One backend, two frontends, one source of truth. Everything either dashboard
shows is a read from the same REST API — there's no separate database per
frontend, no cache to go stale between them.

---

## Quick start (local)

```bash
git clone <your-repo-url>
cd agentic-cost-router
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Terminal 1 — backend
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Streamlit dashboard
streamlit run dashboard.py
```

Open `http://localhost:8000/dashboard` (HTML dashboard) and
`http://localhost:8501` (Streamlit) — sign up in either one (it's a shared
backend, but separate accounts per email), send a prompt, watch the ticket
render with tokens, cost, and latency.

### Docker

```bash
docker compose up --build
```
Brings up the API, Streamlit dashboard, Prometheus, and Grafana together —
see `docker-compose.yml` for exact ports.

---

## Deployment

The backend + HTML dashboard deploy as a single service on **Render**
(`render.yaml` is a ready-to-use Blueprint); the Streamlit dashboard deploys
separately on **Streamlit Cloud**, pointed at the Render URL via the
`ROUTER_API_BASE` secret. Full step-by-step instructions, including the
Render free-tier persistent-disk caveat and a Prometheus/Grafana Cloud setup
guide, are in [`DEVELOPER.md`](./DEVELOPER.md).

---

## Billing / upgrades

Every account gets 5 free `/v1/route` calls, then `POST /v1/auth/upgrade` is
required. **This is currently a mock** — it flips the account to unlimited
with no real charge taken, clearly marked as such in the code and the UI.
Wiring up real Stripe billing is the natural next step; see
[`DEVELOPER.md`](./DEVELOPER.md) for where that hook lives.

---

## Tech stack

FastAPI · SQLite · Streamlit · Plotly · `prometheus-client` · vanilla
JS/HTML for the second dashboard · `tiktoken` for exact token counts ·
OpenAI + Anthropic SDKs for live model calls.

## License

Add a license of your choice (MIT is a reasonable default for a portfolio
project) — none is currently specified.
