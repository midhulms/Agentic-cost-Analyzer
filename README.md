# Agentic Cost Router

**Every prompt, routed to an agent, priced to the token.**

A small, fully working system that sits in front of an LLM call and decides,
per prompt, whether it actually needs a frontier model, or whether a cheaper
model would do the same job for a fraction of the cost. Every decision,
token count, and dollar amount is logged and shown back to you, not just
estimated.

**Live demo:** `https://agentic-cost-router.onrender.com/dashboard`
**API docs:** `https://agentic-cost-router.onrender.com/docs`

> Free tier note: the demo above resets its usage data whenever the service
> redeploys or wakes up from being idle. That is a hosting limitation, not a
> bug. See [Deployment](#deployment) below, and the full walkthrough in
> [`DEMO_GUIDE.md`](./DEMO_GUIDE.md).

---

## Demo

![Agentic Cost Router demo](./demo.gif)

A full walkthrough, covering routing logic, live agent switching, and a real
Hugging Face call end to end, is linked below once recorded. To add your own
recording:

1. Record a short screen capture (OBS, QuickTime, or your OS's built-in
   recorder all work fine) showing a prompt being dispatched, the agent
   card and cost ticket updating, and the Prometheus/Grafana dashboards if
   you have them running.
2. Upload it to YouTube (unlisted is fine for a portfolio link), or convert
   it to a short looping GIF with a tool such as `ffmpeg` or
   [Gifski](https://gif.ski/), and save it as `demo.gif` in the repository
   root so the embed above renders directly on GitHub.
3. Replace the placeholder link below with your own YouTube URL.

📺 **[Watch the full walkthrough on YouTube](your-youtube-link-here)**

---

## What it actually does

1. **Scores prompt complexity** (0.0 to 1.0) using structural signals:
   length, reasoning or planning keywords, code fences, multi-step language.
   No LLM call is needed just to make this decision.
2. **Routes** the prompt to a cheap tier or a frontier tier based on that
   score, and attributes it to one of six named agent personas (Compiler,
   Atlas, Prism, Voyager, Sparrow, Echo) chosen by what the prompt looks
   like it needs.
3. **Calls the model for real.** Plug in your own OpenAI, Anthropic, or
   **Hugging Face** API key and it dispatches a genuine API call, not a
   canned response. Hugging Face is the free option: create a token at
   [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
   (no card required) and it runs real Llama, Qwen, DeepSeek, and gpt-oss
   models through HF's
   [Inference Providers](https://huggingface.co/docs/inference-providers)
   router. New accounts get free monthly credits. No key at all? It returns
   a clearly labeled mock reply instead, so the whole flow still works with
   zero setup.
4. **Counts tokens exactly** via `tiktoken` when available, provider
   reported usage when the API returns it, or a documented approximation as
   a last resort. It tells you which method was used for every single
   response.
5. **Prices every request** against a small model pricing catalog and shows
   input cost, output cost, and, for cheap-routed requests, what the same
   prompt would have cost on the frontier tier instead. "Money saved" is a
   real number, not a marketing one.
6. **Accounts require login**, with 5 free requests per account before a
   (currently mock) upgrade is required. See [Billing](#billing--upgrades).
7. **Two dashboards, one backend:** a dependency-free HTML page served
   directly by the API (`/dashboard`) and a separate Streamlit app
   (`dashboard.py`). Both read and write the same data through the same
   REST API.
8. **Per-account usage tracking:** each logged-in user sees their own
   request count, tokens, and spend by default, with a one-click toggle to
   view the combined "everyone" total instead.

---

## Architecture

```
                     +----------------------+
                     |   FastAPI backend    |
  HTML dashboard --->|   app/main.py        |<--- Streamlit dashboard
  (static/           |                       |     (dashboard.py)
   dashboard.html)   |   auth.py   (login,   |
                      |   sessions, quota)    |
                      |   router.py (route    |
                      |   + dispatch)         |
                      |   complexity.py       |
                      |   providers.py        |
                      |   (OpenAI/Anthropic/  |
                      |    HF call)           |
                      |   cost_tracker.py     |
                      |   (SQLite log)        |
                      |   metrics.py          |
                      |   (Prometheus)        |
                      +-----------+-----------+
                                  |
                         SQLite (data/cost_router.db)
                                  |
                          GET /metrics ---> Prometheus ---> Grafana
```

One backend, two frontends, one source of truth. Everything either
dashboard shows is a read from the same REST API. There is no separate
database per frontend, and no cache to go stale between them.

---

## Agents: what actually differs, and what doesn't

Six named personas sit on top of the router: **Compiler, Atlas, Prism,
Voyager, Sparrow, Echo**. It is worth being precise about what they are,
because it is easy to assume they are six separately prompted sub-agents.
They are not.

**What is real:** each persona is picked from complexity signals
`complexity.py` already computed to decide the cost tier, so selecting an
agent costs zero extra tokens and makes zero extra model calls. See
`app/agents.py::pick_agent()`.

| Your prompt contains... | Signal (`complexity.py`) | Agent picked |
|---|---|---|
| `` ``` ``, `def `, `SELECT `, a function signature | `contains_code` | **Compiler**, Code Agent |
| "step by step", "then", "plan", "workflow" | `multi_step_language` | **Atlas**, Planner Agent |
| "why", "compare", "explain", "trade-off" | `reasoning_language` | **Prism**, Analyst Agent |
| "summarize", "tl;dr", "translate" | keyword match, independent of the router | **Echo**, Summary Agent |
| Long prompt (150+ words) or several `?` marks | `length_words`, `question_count` | **Voyager**, Deep-Dive Agent |
| None of the above; short, single-intent | (default) | **Sparrow**, Quick-Reply Agent |

**What is not real, by design:** the agent label never touches
`app/providers.py::call_model()`. Every agent sends the exact same
`req.prompt` to the exact same model. There is no per-agent system prompt,
temperature, or token budget. Cost is determined entirely by **which
model** (`model_used`) and **how many tokens** went in and out; see
`app/router.py::_cost_breakdown()`. The agent layer is free organization on
top of one honest cost model, not six separately billed AI systems.

Want per-agent behavior to actually diverge (different system prompts, a
different `max_tokens` cap for Sparrow versus Voyager, and so on)? That is
a natural next step. The hook point is `call_model()` in `providers.py`,
which would need an `agent_key` parameter threaded through from
`router.py`.

---

## Quick start (local, no Docker)

```bash
git clone <your-repo-url>
cd agentic-cost-router
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Terminal 1: backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: Streamlit dashboard
streamlit run dashboard.py
```

Open `http://localhost:8000/dashboard` (HTML dashboard) and
`http://localhost:8501` (Streamlit). Sign up in either one (it is a shared
backend, but a separate account per email), send a prompt, and watch the
ticket render with tokens, cost, and latency. No API keys are required; the
app runs entirely in mock mode out of the box.

For the fully literal, click-by-click version of every step below,
including Docker, Prometheus, Grafana, and deploying online, see
[`DEMO_GUIDE.md`](./DEMO_GUIDE.md).

### Docker

```bash
cp .env.example .env
docker compose up --build
```

Brings up the API, the Streamlit dashboard, Prometheus, and Grafana
together. Prometheus and Grafana are pre-wired: Grafana auto-loads
Prometheus as a data source and a starter dashboard on first launch, no
manual setup required. See `docker-compose.yml` for exact ports, and
[`DEMO_GUIDE.md`](./DEMO_GUIDE.md) for the full walkthrough with expected
output at each step.

---

## Deployment

The backend and HTML dashboard deploy as a single service on **Render**
(`render.yaml` is a ready-to-use Blueprint); the Streamlit dashboard deploys
separately on **Streamlit Cloud**, pointed at the Render URL via the
`ROUTER_API_BASE` secret. Full step-by-step instructions, including the
Render free-tier persistent-disk caveat and the Prometheus/Grafana setup,
are in [`DEMO_GUIDE.md`](./DEMO_GUIDE.md). Architecture-level and
contributor-facing notes live in [`DEVELOPER.md`](./DEVELOPER.md).

---

## Running a real model for free (Hugging Face)

You do not need an OpenAI or Anthropic subscription to see live calls
working:

1. Go to [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens),
   sign in (free account), and create a **fine-grained token** with the
   "Make calls to Inference Providers" permission checked.
2. Either:
   - Paste it into the **Hugging Face token** field in the dashboard's key
     bar and hit Dispatch. It is used only for that one request and is
     never stored, or
   - Put it in `.env` as `HF_API_KEY=hf_...` so every request can use it
     without re-pasting.
3. Pick one of the Hugging Face models in the "Force model" dropdown:
   `meta-llama/Llama-3.1-8B-Instruct` (cheap tier), `Qwen/Qwen2.5-72B-Instruct`
   or `meta-llama/Llama-3.3-70B-Instruct` (mid tier), or
   `deepseek-ai/DeepSeek-V3-0324` / `openai/gpt-oss-120b` (frontier tier),
   and dispatch a prompt.
4. The reply is tagged **LIVE** (not MOCK), token counts come straight from
   the provider's own `usage` field (`provider-api-exact`), and the cost
   ticket prices it at the underlying provider's normal per-token rate. HF
   free-tier credits typically cover this at $0 actual cost while they
   last.

Behind the scenes this hits
`https://router.huggingface.co/v1/chat/completions`, an OpenAI-compatible
endpoint HF exposes in front of multiple backend providers (Together,
Fireworks, Cerebras, and others). See
`app/providers.py::call_huggingface_model` and the
[Inference Providers docs](https://huggingface.co/docs/inference-providers)
for details. A bad or missing token, an unavailable model, or a rate limit
all come back as a clearly labeled `[hugging face call failed: ...]`
message in the response instead of a crash, so you can see exactly what
went wrong.

---

## Billing / upgrades

Every account gets 5 free `/v1/route` calls, then `POST /v1/auth/upgrade`
is required. **This is currently a mock.** It flips the account to
unlimited with no real charge taken, clearly marked as such in the code and
the UI. Wiring up real Stripe billing is the natural next step; see
[`DEVELOPER.md`](./DEVELOPER.md) for where that hook lives.

---

## Testing

```bash
pip install -r requirements.txt
pytest tests/ -q
```

21 tests cover complexity scoring, routing decisions, and metrics.

---

## Tech stack

FastAPI, SQLite, Streamlit, Plotly, `prometheus-client`, vanilla JS/HTML
for the second dashboard, `tiktoken` for exact token counts, and the
OpenAI and Anthropic SDKs plus Hugging Face Inference Providers (free tier)
for live model calls.

## Author

Built by **Cryzal & Midhul**.

## License

MIT, see [`LICENSE`](./LICENSE). Free to use, modify, and build on for your
own projects; just keep the copyright notice.
