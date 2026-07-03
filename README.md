# Agentic Cost Router

**Author:** Cryzal/midhul
**Live demo:** _add your Render URL here once deployed, e.g. https://agentic-cost-router.onrender.com/dashboard_
**Note:** the free hosting tier sleeps after 15 min idle and resets the SQLite file on redeploy/spin-down — send a few prompts after the first load to repopulate the charts. Fine for a portfolio demo, not meant for persistent production data.


## Preview  

![App view]([Screenshot from 2026-07-03 05-13-49.png](https://github.com/midhulms/Agentic-cost-Analyzer/blob/main/Screenshot%20from%202026-07-03%2005-13-49.png)
![Dashboard Preview](https://github.com/midhulms/Agentic-cost-Analyzer/blob/main/Screenshot%20from%202026-07-03%2005-14-14.png)
![Dashboard Preview](https://github.com/midhulms/Agentic-cost-Analyzer/blob/main/Screenshot%20from%202026-07-03%2005-14-33.png)
![Dashboard Preview](https://github.com/midhulms/Agentic-cost-Analyzer/blob/main/Screenshot%20from%202026-07-03%2005-24-02.png)
![Dashboard Preview](https://github.com/midhulms/Agentic-cost-Analyzer/blob/main/Screenshot%20from%202026-07-03%2005-24-31.png)

)


---


A small, honest version of what "Bud"-style Hybrid AI routing does: send most
requests to a cheap/open-weight model, escalate to a frontier model only when
a prompt actually looks like it needs one, and track how much that saves.

This is not a clone of any commercial product — it's a from-scratch reference
implementation you can explain in an interview line by line: how the
complexity score is computed, how routing decisions are made, how cost is
estimated, and where the real gaps are if you were to productionize it.

## Architecture

```
client -> POST /v1/route -> complexity.score(prompt)
                                   |
                         < threshold ?        >= threshold ?
                                |                    |
                        cheap provider        frontier provider
                     (mock / Ollama)        (mock / Anthropic API)
                                \                    /
                                 -> cost_tracker.log_request() -> SQLite
                                                |
                                      dashboard.py (Streamlit)
```

- **`app/complexity.py`** — transparent heuristic scorer (length, multi-step
  language, reasoning markers, code, question count). No black box: you can
  point to the exact weights.
- **`app/agents.py`** — maps those same complexity signals to a named agent
  persona (Compiler, Atlas, Prism, Voyager, Sparrow) so every request is
  attributed to a "who," not just a model string.
- **`app/providers.py`** — adapters for the cheap path (mock or local Ollama)
  and frontier path (mock or Anthropic API), plus exact token counting via
  `tiktoken` and plain-English cost/token explanations. Runs fully in "mock"
  mode with zero API keys, so it's demoable anywhere.
- **`app/router.py`** — the routing decision, agent selection, and full
  cost/baseline calculation.
- **`app/cost_tracker.py`** — SQLite log of every request (now including
  agent + token-counting method), used to compute savings vs. an
  "always frontier" baseline, and per-agent / per-model rollups.
- **`dashboard.py`** — the original Streamlit view: total requests, cost
  saved, route split, a box to try prompts live, and a recent-requests table.
- **`static/dashboard.html`** — the new "Agent Dispatch" dashboard (see below).

## Exact token counts, not guesses

Earlier versions estimated tokens as `words * 1.3`. That's now only a
last-resort fallback. The default counter is
[`tiktoken`](https://github.com/openai/tiktoken)'s `cl100k_base` encoding —
free, open-source, and runs entirely offline once its vocab file is cached
locally (no API key, no per-call cost). It's the same encoding family used
by GPT-3.5/GPT-4, so it gives an exact count for *something real*, not an
approximation, even in mock mode. When a real Anthropic API call is made,
the response includes billed usage directly, which always wins over any
local count.

Every `/v1/route` response includes `token_count_method` so you always know
which of the three applies:
- `provider-api-exact` — straight from the provider's billed usage.
- `tiktoken-cl100k` — exact local tokenization, free, no network call.
- `whitespace-approx` — fallback only if `tiktoken` itself can't load.

> Note: `tiktoken` downloads its encoding file from a public OpenAI-hosted
> URL the first time it's used, then caches it locally — after that first
> run it's fully offline. If you're on a fully air-gapped machine, the
> counter automatically falls back to `whitespace-approx` and tells you so.

## Named agents, not just model strings

Every request is attributed to one of five agent personas, picked from the
same complexity signals the router already computes — no extra tokens, no
separate classifier:

| Agent | Role | Trigger |
|---|---|---|
| **Compiler** | Code Agent | prompt contains code / a function / a query |
| **Atlas** | Planner Agent | prompt asks for a plan, workflow, or steps |
| **Prism** | Analyst Agent | prompt asks to compare, evaluate, or explain why |
| **Voyager** | Deep-Dive Agent | long prompt or several questions at once |
| **Sparrow** | Quick-Reply Agent | short, single-intent prompt, no signals fired |

`GET /v1/agents` returns the full roster; `GET /v1/stats/agents` and
`GET /v1/stats/models` return spend and token totals grouped by agent and by
model, for whatever dashboard you point at the API.

## The new dashboard: Agent Dispatch

`static/dashboard.html`, served at `GET /dashboard`, is a from-scratch,
dependency-free (just Chart.js from a CDN) dashboard built around a
dispatch/ops-desk metaphor:

- **Agent roster cards** — who's on duty, how many requests, tokens, and
  dollars each agent has handled.
- **A printed cost "ticket"** for every prompt you send — token counts (with
  the exact/approx badge), a line-by-line cost breakdown (input cost +
  output cost = total), and two plain-English explanations: *why this
  agent/route* and *why this cost*.
- **Charts** — cost by agent, cheap/frontier split, cost by model.
- **A recent-dispatch log**, terminal-style.

It talks to the same `/v1/*` endpoints as the Streamlit dashboard, so both
can run side by side. Open it directly at `http://localhost:8000/dashboard`
once the API is running — no separate process needed.


## Metrics & Monitoring (Prometheus + Grafana)

Every routed request is also pushed to `app/metrics.py`, which exposes it at
`GET /metrics` in standard Prometheus exposition format — the same shape as
a production LLM gateway's metrics endpoint, just scoped to this one app
instead of a fleet of gateways.

Four metrics, each labeled by `route` / `model` (and `agent` for request
counts):

| Metric | What it is |
|---|---|
| `router_requests_total` | Counter, labeled `route`, `model`, `agent` |
| `router_tokens_total` | Counter, labeled `route`, `model`, `direction` (input/output) |
| `router_cost_usd_total` | Counter, labeled `route`, `model` |
| `router_baseline_cost_usd_total` | Counter — same requests, priced as if every one went to the frontier model (this is what "savings" is computed against) |
| `router_request_latency_seconds` | Histogram, labeled `route`, `model` |

```bash
curl http://localhost:8000/metrics
```

### Run Prometheus + Grafana alongside the app

```bash
docker compose up --build
```

This now also starts:
- **Prometheus** on `http://localhost:9090` — scrape config already points
  at the API (`monitoring/prometheus.yml`), nothing to configure.
- **Grafana** on `http://localhost:3000` (login: `admin` / `admin`)

In Grafana: Connections → Data sources → Add data source → Prometheus →
URL `http://prometheus:9090` → Save & test. Then build panels (or import a
dashboard JSON) using queries like:

```promql
sum(router_cost_usd_total)                                  # total spend
sum(rate(router_tokens_total[5m])) by (direction)            # token rate
1 - (sum(router_cost_usd_total) / sum(router_baseline_cost_usd_total))  # % saved
histogram_quantile(0.95, rate(router_request_latency_seconds_bucket[5m]))  # p95 latency
```

The `router_cost_usd_total` vs `router_baseline_cost_usd_total` pair is the
whole point of the project: subtract one from the other and you have a
real, provable savings number instead of a claimed one.


## Honesty about the claims

This scores complexity with a rules-based heuristic, not a trained
classifier — it's a legible starting point, not a "no loss in accuracy"
guarantee. If you extend this for a thesis or portfolio piece, the natural
next step is logging (prompt, route, human-graded quality) and training a
small classifier on that data, then A/B testing the threshold.

---

## Step-by-step: run it locally

```bash
# 1. Get the code onto your machine (see git steps below if starting fresh)
cd agentic-cost-router

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure (mock mode works with no edits)
cp .env.example .env

# 5. Run the API
uvicorn app.main:app --reload --port 8000

# 6. In a second terminal, run the dashboard
streamlit run dashboard.py
```

Open `http://localhost:8501` for the Streamlit dashboard,
`http://localhost:8000/dashboard` for the new Agent Dispatch dashboard, or
`http://localhost:8000/docs` for the interactive API docs.

### Try it from the command line

```bash
curl -X POST http://localhost:8000/v1/route \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the capital of France?"}'

curl -X POST http://localhost:8000/v1/route \
  -H "Content-Type: application/json" \
  -d '{"prompt": "First analyze our Q3 churn drivers, then compare them against Q2, explain the trade-offs of each retention strategy step by step, and recommend which to prioritize and why."}'

curl http://localhost:8000/v1/stats
```

### Wiring in real models (optional)

- **Cheap path via Ollama**: install [Ollama](https://ollama.com), run
  `ollama pull llama3.1:8b`, then set `CHEAP_PROVIDER=ollama` in `.env`.
- **Frontier path via Anthropic**: set `FRONTIER_PROVIDER=anthropic` and
  `ANTHROPIC_API_KEY=...` in `.env`.

### Run with Docker

```bash
docker compose up --build
```
API on `:8000`, dashboard on `:8501`.

### Run the tests

```bash
pytest -v
```

---

## Step-by-step: get this into git and onto GitHub (Linux)

```bash
cd agentic-cost-router

git init
git config user.name "Cryzal"
git config user.email "your-email@example.com"

git add .
git commit -m "Initial commit: agentic cost router MVP"
```

Push with GitHub CLI:
```bash
sudo apt install gh    # if not already installed
gh auth login
gh repo create agentic-cost-router --public --source=. --remote=origin --push
```

Or manually — create an empty repo named `agentic-cost-router` on github.com, then:
```bash
git remote add origin git@github.com:YOUR-USERNAME/agentic-cost-router.git
git branch -M main
git push -u origin main
```

CI (`.github/workflows/ci.yml`) runs `pytest` and a Trivy container scan on
every push automatically — no extra setup needed once it's on GitHub, same
pattern as your Crop Price Intelligence Platform pipeline.

### Ongoing workflow

```bash
git checkout -b feature/trained-classifier
# ...make changes...
git add .
git commit -m "Replace heuristic with trained complexity classifier"
git push -u origin feature/trained-classifier
# open a PR on GitHub, merge into main once CI is green
```

## Suggested next steps for a portfolio version

1. Swap the heuristic for a small trained classifier (log real routing
   decisions + outcomes first, then train on that).
2. Add a `/v1/feedback` endpoint so a human can flag a misrouted request —
   this is the data you'd need for step 1.
3. Add per-tenant or per-API-key cost limits.
4. Deploy the API on Streamlit Cloud or Fly.io alongside your existing Crop
   Price project so both are live, linkable portfolio pieces.
