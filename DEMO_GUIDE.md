# Demo Guide: running everything, step by step

This walks through every way to run Agentic Cost Router: local (no Docker),
local with Docker (API, Streamlit, Prometheus, Grafana all together), and
deployed online (Render + Streamlit Cloud). Every command below has been
run against this exact codebase; the sample output shown is real, not
illustrative.

If you only want the short version, see the Quick Start section in
`README.md`. This file is the literal, nothing-skipped version.

---

## Part 1: Run it locally, no Docker, no API keys

This is the fastest way to see the whole app working, entirely in mock
mode.

1. Open a terminal and clone the repository:
   ```bash
   git clone <your-repo-url>
   cd agentic-cost-router
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
   On Windows (PowerShell), activate with `venv\Scripts\Activate.ps1`
   instead.

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Copy the example environment file. You do not need to edit it; every
   provider defaults to `mock` so the app runs with zero API keys.
   ```bash
   cp .env.example .env
   ```

5. Start the backend:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   You should see:
   ```
   INFO:     Started server process
   INFO:     Waiting for application startup.
   INFO:     Application startup complete.
   INFO:     Uvicorn running on http://127.0.0.1:8000
   ```

6. In a second terminal, confirm the API is alive:
   ```bash
   curl http://localhost:8000/health
   ```
   Expected output:
   ```json
   {"status":"ok"}
   ```

7. Create an account and capture the login token:
   ```bash
   curl -s -X POST http://localhost:8000/v1/auth/signup \
     -H "Content-Type: application/json" \
     -d '{"email":"you@example.com","password":"a-real-password"}'
   ```
   This returns a token and your fresh account, with 5 free requests:
   ```json
   {"token":"<a long random string>","user":{"id":1,"email":"you@example.com","free_uses_remaining":5,"is_paid":false}}
   ```
   Copy the token value, you will need it for the next step.

8. Send a prompt through the router (replace `<TOKEN>` with the value from
   step 7):
   ```bash
   curl -s -X POST http://localhost:8000/v1/route \
     -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"prompt":"Write a step by step plan to migrate a database, then explain the trade-offs."}'
   ```
   You will get back a full ticket: which agent picked it up, which model
   it routed to, exact token counts, cost, and a plain-English routing
   reason. In mock mode (no keys set) `is_live_call` will be `false` and
   the reply is clearly labeled as a mock response.

9. Open the dashboards in a browser:
   - HTML dashboard, served directly by the API: `http://localhost:8000/dashboard`
   - Interactive API docs (Swagger UI): `http://localhost:8000/docs`
   - Streamlit dashboard, in a third terminal:
     ```bash
     streamlit run dashboard.py
     ```
     then open `http://localhost:8501`

10. Sign up or log in from either dashboard's UI, dispatch a few prompts
    from the text box, and watch the agent card, cost ticket, and charts
    update live. Both dashboards read the same SQLite database through the
    same API, so numbers always match between them.

---

## Part 2: Run everything with Docker (API, Streamlit, Prometheus, Grafana)

This brings up all four services in one command, wired together on an
internal Docker network.

1. Make sure Docker Desktop (or the Docker Engine + Compose plugin on
   Linux) is installed and running.

2. From the repository root, copy the environment file. `docker-compose.yml`
   loads `.env` into the API container, so this file has to exist even if
   you leave every value at its default:
   ```bash
   cp .env.example .env
   ```

3. Build and start every service:
   ```bash
   docker compose up --build
   ```
   The first run takes a few minutes while the Python image builds. Once
   it settles, you will see four services logging in the same terminal:
   `api`, `dashboard`, `prometheus`, and `grafana`.

4. Open each service in a browser once the logs settle:
   | Service | URL | Notes |
   |---|---|---|
   | API health check | `http://localhost:8000/health` | Should return `{"status":"ok"}` |
   | HTML dashboard | `http://localhost:8000/dashboard` | Same page as the no-Docker run |
   | API docs | `http://localhost:8000/docs` | |
   | Streamlit dashboard | `http://localhost:8501` | Talks to the `api` service over the internal Docker network |
   | Prometheus | `http://localhost:9090` | Go to **Status -> Targets**; the `agentic-cost-router` job should show as `UP` |
   | Grafana | `http://localhost:3000` | Log in with `admin` / `admin` (Grafana will ask you to set a new password, or you can skip that step) |

5. Grafana is pre-provisioned, so there is nothing to configure by hand:
   - The Prometheus data source is added automatically on first boot
     (`monitoring/grafana/provisioning/datasources/prometheus.yml`), and
     already points at `http://prometheus:9090`, the internal Docker
     network address of the Prometheus service.
   - A starter dashboard named **Agentic Cost Router** is loaded
     automatically (`monitoring/grafana/dashboards/agentic-cost-router.json`)
     with panels for requests by route, total cost, estimated savings,
     tokens by direction, request latency (p50/p95), requests by agent,
     and cost by model.
   - To see it: **Dashboards** in the left sidebar, then open **Agentic
     Cost Router**. Send a few prompts through either dashboard first so
     there is data to plot.

6. Data persistence while running with Docker Compose: the SQLite database
   lives at `./data/cost_router.db` on your host machine, mounted into the
   `api` container at `/app/data` (see the `volumes:` entry for the `api`
   service in `docker-compose.yml`). Stopping and restarting the stack with
   `docker compose down` and `docker compose up` again keeps all accounts
   and request history, because the data lives on the host, not inside the
   container.

7. To stop everything:
   ```bash
   docker compose down
   ```
   Add `-v` if you also want to wipe the named `grafana-data` volume
   (Grafana's own settings, not your app data, which lives in `./data` on
   the host either way).

---

## Part 3: Deploy the API online (Render)

1. Push the repository to GitHub. Render deploys from a Git repo, not a
   zip upload:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<you>/agentic-cost-router.git
   git push -u origin main
   ```

2. Go to [dashboard.render.com](https://dashboard.render.com), sign in
   (GitHub login is the fastest option), and click **New +** then
   **Blueprint**.

3. Connect the GitHub repository you just pushed. Render reads
   `render.yaml` automatically and pre-fills the service: Docker build,
   `/health` check path, and the `mock` provider environment variables.
   Click **Apply** to create the service.

4. Once the first build finishes (a few minutes), open your service's
   **Environment** tab if you want live model calls instead of mock
   replies, and add any of the following:
   | Key | Value |
   |---|---|
   | `CHEAP_PROVIDER` | `mock` (or `ollama` / `mistral`) |
   | `FRONTIER_PROVIDER` | `mock` (or `anthropic` / `openai`) |
   | `ANTHROPIC_API_KEY` | only needed if `FRONTIER_PROVIDER=anthropic` |
   | `OPENAI_API_KEY` | only needed if you use OpenAI |
   | `HF_API_KEY` | free, get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |

5. Confirm the deploy is live:
   ```
   https://<your-service-name>.onrender.com/health       ->  {"status":"ok"}
   https://<your-service-name>.onrender.com/dashboard    ->  the HTML dashboard
   https://<your-service-name>.onrender.com/metrics      ->  Prometheus exposition text
   ```

6. **Free-tier data persistence, read this before relying on the data.**
   Render's free plan gives the container no persistent disk. Every
   redeploy, and every cold start after the service spins down from
   inactivity, wipes the container's filesystem, including
   `data/cost_router.db`. Every account and every logged request resets to
   zero. This is expected behavior on the free tier, not a bug. To make
   data persist:
   - **Simplest, costs money:** upgrade the service to a paid instance
     type, then uncomment the `disk:` block already sitting (commented
     out) at the bottom of `render.yaml`, with `mountPath: /app/data`.
   - **Free, more work:** point `db_path` in `app/config.py` (or the
     `DB_PATH` environment variable) at an external database, such as
     Render's own free-tier PostgreSQL, Supabase, or Turso, instead of
     local SQLite.

---

## Part 4: Deploy the Streamlit dashboard online (Streamlit Community Cloud)

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with
   GitHub.

2. Click **New app**, and fill in:
   - **Repository:** `<you>/agentic-cost-router`
   - **Branch:** `main`
   - **Main file path:** `dashboard.py`

3. Before deploying, open **Advanced settings -> Secrets** and paste:
   ```toml
   ROUTER_API_BASE = "https://<your-service-name>.onrender.com"
   ```
   This is what `dashboard.py` reads to find your API. Without it, the
   dashboard falls back to `http://localhost:8000`, which will not exist
   once it is running online.

4. Click **Deploy**. You will get a URL such as
   `https://<something>.streamlit.app`. Open it, sign up or log in, and
   confirm requests dispatched there show up in the Render-hosted API's
   `/v1/stats` endpoint as well, since both dashboards share the same
   backend and the same accounts.

---

## Part 5: Prometheus and Grafana against your live, online API

You do not need Docker to monitor a deployed instance; `/metrics` is a
plain public endpoint.

**Quick check, no extra infrastructure:**
```bash
curl https://<your-service-name>.onrender.com/metrics
```
This alone is enough to confirm monitoring is wired up, if you just want to
show it exists without standing up Grafana.

**Full dashboard, using Grafana Cloud's free tier:**
1. Sign up at [grafana.com](https://grafana.com) and open your Grafana
   Cloud stack.
2. Go to **Connections -> Add new connection**, search for **Prometheus**,
   and choose the hosted scrape option.
3. Set the scrape target to your deployed `/metrics` URL:
   ```
   https://<your-service-name>.onrender.com/metrics
   ```
4. Set a scrape interval of 15 to 30 seconds; that is plenty for a demo
   app.
5. Once data is flowing, go to **Dashboards -> New -> Add visualization**,
   pick your Prometheus data source, and use queries such as:
   ```promql
   sum(router_cost_usd_total)
   sum(rate(router_tokens_total[5m]))
   1 - (sum(router_cost_usd_total) / sum(router_baseline_cost_usd_total))
   ```
   Metric names come straight from `app/metrics.py`; check there if a
   query returns no series.

Or, if you would rather not use a hosted Grafana at all, import
`monitoring/grafana/dashboards/agentic-cost-router.json` into any Grafana
instance by hand (**Dashboards -> New -> Import**, upload the JSON file,
and point it at a Prometheus data source scraping your deployed
`/metrics` URL).

---

## Part 6: Testing checklist

Run the automated test suite first:
```bash
pip install -r requirements.txt
pytest tests/ -q
```
Expected output:
```
21 passed
```

Then walk through this manual checklist, once locally and once against
your deployed URLs:

- [ ] `GET /health` returns `{"status":"ok"}`.
- [ ] Sign up with a new email through either dashboard succeeds and shows
      5 free requests remaining.
- [ ] Logging in with the wrong password is rejected with a clear error,
      and the correct password logs in.
- [ ] Dispatching a prompt returns an agent name, a model name, exact
      token counts, and a cost breakdown.
- [ ] After 5 requests on a free account, the 6th is rejected with a 402
      and a message pointing at `/v1/auth/upgrade`.
- [ ] Calling `/v1/auth/upgrade` flips the account to unlimited and the
      6th request (and beyond) now succeeds.
- [ ] `/v1/stats/me` only reflects your own account's requests; `/v1/stats`
      reflects every account combined.
- [ ] Restarting the app (or the Docker stack) keeps existing accounts and
      request history, since the SQLite file lives outside the container.
- [ ] `/metrics` returns Prometheus-format text, and (if running the full
      Docker stack) the Grafana dashboard's panels populate after a few
      prompts.

---

## Reducing the demo to a video or GIF

For a recording that shows the whole story in under two minutes:

1. Start with `docker compose up --build` already running in a terminal
   window, so Prometheus and Grafana are visible in the background.
2. Sign up on the HTML dashboard, send two or three prompts with visibly
   different complexity (a one-line question, a "step by step" planning
   prompt, and a prompt containing a code block), and pause on each agent
   card long enough to read the routing reason.
3. Switch to the Grafana dashboard and show the cost and token panels
   updating.
4. Paste a free Hugging Face token into the key bar, force a Hugging Face
   model, and dispatch one more prompt to show a real, non-mock API call
   with `is_live_call: true`.
5. Export the recording as an MP4 for YouTube, or trim it down to a short
   loop and convert it to `demo.gif` for the README embed.
