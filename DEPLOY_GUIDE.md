# Deploying Agentic Cost Router — step by step

Your app has **two pieces** that need to be deployed *separately*, then pointed at each other:

| Piece | What it is | Where it typically lives |
|---|---|---|
| **API + `dashboard.html`** | FastAPI app (`app/main.py`). Serves the JSON API *and* the "Agent Dispatch" HTML page at `/dashboard`. | Render (you're already on `agentic-cost-router.onrender.com`) |
| **`dashboard.py`** | The Streamlit dashboard. | Streamlit Community Cloud (free) |

Both talk to the **same backend and the same user accounts** — that's what makes the single-login fix work. Do part 1 first, since part 2 needs its URL.

---

## Part 1 — Deploy the API (Render)

1. **Push your code to GitHub** (Render deploys from a repo, not a zip upload).
   ```bash
   git init                      # skip if already a repo
   git add .
   git commit -m "Single sign-on + chat-style output box"
   git branch -M main
   git remote add origin https://github.com/<you>/agentic-cost-router.git
   git push -u origin main
   ```

2. **Render dashboard → New → Blueprint.** Point it at your repo. Render will read `render.yaml` and pre-fill everything (it already defines the Docker build, `/health` check, and the mock-provider env vars).
   - If you'd rather do it by hand: **New → Web Service → Docker**, root = repo root, `dockerfilePath` = `./Dockerfile`, health check path = `/health`.

3. **Environment variables** (Render → your service → Environment). The blueprint sets these already; add real ones if/when you want live model calls instead of mock replies:
   | Key | Value |
   |---|---|
   | `CHEAP_PROVIDER` | `mock` (or `ollama` / `mistral`) |
   | `FRONTIER_PROVIDER` | `mock` (or `anthropic` / `openai`) |
   | `COMPLEXITY_THRESHOLD` | `0.55` |
   | `ANTHROPIC_API_KEY` | *(only if `FRONTIER_PROVIDER=anthropic`)* |
   | `OPENAI_API_KEY` | *(only if you use OpenAI)* |
   | `HF_API_KEY` | *(free — get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens); not tied to `CHEAP_PROVIDER`/`FRONTIER_PROVIDER`, just pick a `meta-llama/...`, `Qwen/...`, `deepseek-ai/...`, or `openai/gpt-oss-*` model via "Force model" in the dashboard, or paste the token directly into the dashboard's key bar per-request instead of setting it here)* |

4. **Deploy.** First deploy takes a few minutes (Docker build). When it's green, confirm:
   ```
   https://agentic-cost-router.onrender.com/health      -> {"status":"ok"}
   https://agentic-cost-router.onrender.com/dashboard    -> the Agent Dispatch page
   ```

5. ⚠️ **Read this — it's very likely the actual cause of your "Incorrect email or password" screenshot.**
   Your `render.yaml` is on Render's **free plan with no persistent disk**. The user database is a plain SQLite file (`data/cost_router.db`). On the free tier, **every redeploy and every cold-start after the service sleeps from inactivity wipes the filesystem** — all accounts and all usage history reset to zero. So if you signed up a few hours ago and Render spun the service down or redeployed since, that account is simply gone; "incorrect email or password" is expected, not a bug in the login form.
   To make accounts (and usage data) actually persist, do **one** of:
   - **Attach a paid Render Disk** — upgrade the service to a paid instance type, then uncomment the `disk:` block already sitting (commented) in `render.yaml`, mount at `/app/data`. Simplest fix, costs money.
   - **Move to a real database** (free-tier-friendly) — e.g. Render's free PostgreSQL, or Supabase/Turso — and swap the `sqlite3` calls in `app/auth.py` / `app/cost_tracker.py` for that. More work, but survives forever on the free tier.
   Until you do one of these, expect accounts to reset periodically — that's independent of the login/SSO fix below.

---

## Part 2 — Deploy the Streamlit dashboard (Streamlit Community Cloud)

1. Go to **share.streamlit.io** → **New app** (uses the same GitHub repo).
2. Fill in:
   - **Repository**: `<you>/agentic-cost-router`
   - **Branch**: `main`
   - **Main file path**: `dashboard.py`
3. **App settings → Secrets**, paste:
   ```toml
   ROUTER_API_BASE = "https://agentic-cost-router.onrender.com"
   ```
   (This is what `dashboard.py` reads on line ~12-17 to find your API. Without it, it falls back to `http://localhost:8000`, which won't exist online.)
4. **Deploy.** You'll get a URL like `https://<something>.streamlit.app`.

---

## Part 3 — Wire the two together (the single-login fix)

This is the piece that makes "log in once, both pages agree" actually work, since the two apps are on two different domains.

1. Open your **Streamlit app URL**, log in (or sign up) once.
2. In the sidebar you'll now see a button: **"Open Agent Dispatch view ↗"**. That's `dashboard.html` opening with your session token attached in the URL — it logs you in there automatically, no separate form.
3. On `dashboard.html`, near the top, there's now a **"Streamlit dashboard URL"** box (replacing the old login fields). Paste your Streamlit app's URL there once and click **Save** (it's saved in that browser, via `localStorage`, so you only do this once per browser). This is what lets `dashboard.html` build a working "**Open Streamlit dashboard ↗**" link back, and lets the *first* login (if someone starts on this page instead) send them to the right place.
4. **Log out** either from the Streamlit sidebar or from `dashboard.html`'s auth bar. Each also offers a link/caption to log the *other* one out in the same click, so a full logout doesn't require doing it twice.

That's the whole flow: whichever app you log into first hands its token to the other one over the URL; from then on both read/write the exact same account and the exact same "My usage" / "Everyone (global demo)" data, because they're both just calling the one API's `/v1/auth/*` and `/v1/stats*` endpoints.

---

## Part 4 — What changed, if you're comparing to your old copy

- **`static/dashboard.html`**
  - Removed the email/password signup+login form. Replaced with: a locked-out state that links to the Streamlit app, a small "paste a token" fallback for power users/debugging, and automatic pickup of `?token=...` / `?logout=1` from the URL (stripped from the address bar right after).
  - Added a "Streamlit dashboard URL" field so the two pages know how to link to each other (saved in `localStorage`).
  - Replaced the single "last result only" cost ticket with a **scrollable chat-style "Model Output" box** — each dispatch now appends a right-aligned prompt bubble and a left-aligned agent-reply bubble (with a "Dispatching…" placeholder while in flight), so the full conversation stays visible instead of only the most recent reply. The old detailed cost breakdown (tokens, routing reason, cost explanation) is still there, tucked into a **"Full cost ticket"** `<details>` toggle on each reply bubble. A **Clear** button resets the transcript.
- **`dashboard.py`**
  - Added the `?token=...` / `?logout=1` handoff (reads `st.query_params`, validates the token against `/v1/auth/me`, then clears the query string).
  - Added an **"Open Agent Dispatch view ↗"** button in the sidebar once logged in, and a link to log out of that page too.

Nothing in `app/` (the API itself) needed to change — both frontends already called the same `/v1/auth/login`, `/v1/auth/signup`, `/v1/auth/me`, and `/v1/stats*` endpoints; they just weren't sharing the *result* of logging in.

---

## Part 5 — Testing checklist (desktop + online)

**Locally first** (fast to iterate):
```bash
# terminal 1
uvicorn app.main:app --reload --port 8000
# terminal 2
ROUTER_API_BASE=http://localhost:8000 streamlit run dashboard.py
```
- [ ] Open the Streamlit URL, sign up, dispatch a prompt, see it in the chat box style... (that part's actually only on the HTML page — see below)
- [ ] Click "Open Agent Dispatch view ↗" → `http://localhost:8000/dashboard` opens already logged in, same email/quota shown, "My usage" numbers match.
- [ ] On `dashboard.html`, dispatch a prompt → a user bubble + agent-reply bubble appear in "Model Output"; expand "Full cost ticket" to confirm the breakdown is intact.
- [ ] Click "Log out" on `dashboard.html` → back in Streamlit, its own session is untouched (by design — logging out one place doesn't yank the other unless you use the explicit cross-logout link).
- [ ] Use the cross-logout link/button from either side → confirm the *other* app also drops back to logged-out.

**Then online**, same checklist against your real Render + Streamlit Cloud URLs. The one extra thing to check online: after Render's free instance has been idle for a while (spins down), the first request after waking it up can take 30-60s — the app already surfaces this as a warning with a retry button rather than failing silently.
