# Streamlit dashboard for the Agentic Cost Router. Author: Cryzal/midhul
import os
import httpx
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Agentic Cost Router", layout="wide")

from pathlib import Path

_secrets_path = Path(__file__).parent / ".streamlit" / "secrets.toml"
if _secrets_path.exists():
    for _key in ("ROUTER_API_BASE",):
        if _key in st.secrets:
            os.environ.setdefault(_key, st.secrets[_key])
API_BASE = os.environ.get("ROUTER_API_BASE", "http://localhost:8000")

st.title("Agentic Cost Router")
st.caption("Routes prompts by complexity, tracks cost saved vs. always using the frontier model.")
st.info("A more visual, agent-focused view of this same data lives at **/dashboard** on the API "
        f"(e.g. {API_BASE}/dashboard) — cards per agent, a chat-style output box, and charts. "
        "Logging in here also logs you in there (and vice versa) — no separate account needed.")

# ---------------------------------------------------------------------------
# Login / signup gate. POST /v1/route now requires a Bearer token (5 free
# calls per account, then /v1/auth/upgrade is required) -- see app/auth.py.
# Everything below this block is unreachable until st.session_state["token"]
# is set, which happens on a successful login or signup.
# ---------------------------------------------------------------------------
if "token" not in st.session_state:
    st.session_state["token"] = None
    st.session_state["user"] = None

# ---------------------------------------------------------------------------
# Single sign-on with the HTML dashboard (static/dashboard.html, served at
# {API_BASE}/dashboard). That page has no login form of its own anymore --
# it either arrives here already logged in via ?token=... in its own URL,
# or it links back to THIS app with ?token=... after login happens here.
# We mirror that: if this app is opened with ?token=..., adopt that session
# instead of showing the login form, so either app can "start" the login
# and the other one just follows. ?logout=1 clears the session the same
# way. The query params are cleared right after so refreshing the page
# doesn't replay the same action and so tokens don't linger in the URL.
# ---------------------------------------------------------------------------
_qp = st.query_params
if _qp.get("logout") == "1":
    st.session_state["token"] = None
    st.session_state["user"] = None
    st.session_state["last_result"] = None
    st.query_params.clear()
elif _qp.get("token") and st.session_state["token"] is None:
    _incoming_token = _qp["token"]
    try:
        _resp = httpx.get(f"{API_BASE}/v1/auth/me",
                           headers={"Authorization": f"Bearer {_incoming_token}"}, timeout=10)
        if _resp.status_code == 200:
            st.session_state["token"] = _incoming_token
            st.session_state["user"] = _resp.json()
            st.session_state["last_result"] = None
    except Exception:
        pass  # fall through to the normal login form below if this failed
    st.query_params.clear()

def _auth_headers() -> dict:
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}

with st.sidebar:
    st.subheader("Account")
    if st.session_state["token"] is None:
        tab_login, tab_signup = st.tabs(["Log in", "Sign up"])
        with tab_login:
            login_email = st.text_input("Email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_password")
            if st.button("Log in"):
                try:
                    resp = httpx.post(f"{API_BASE}/v1/auth/login",
                                       json={"email": login_email, "password": login_password}, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        st.session_state["token"] = data["token"]
                        st.session_state["user"] = data["user"]
                        st.session_state["last_result"] = None  # fresh account, fresh page -- don't show the previous account's last response
                        st.rerun()
                    else:
                        st.error(resp.json().get("detail", "Log in failed."))
                except Exception as exc:
                    st.error(f"Could not reach {API_BASE} ({exc}).")
        with tab_signup:
            signup_email = st.text_input("Email", key="signup_email")
            signup_password = st.text_input("Password (min 6 chars)", type="password", key="signup_password")
            if st.button("Create account"):
                try:
                    resp = httpx.post(f"{API_BASE}/v1/auth/signup",
                                       json={"email": signup_email, "password": signup_password}, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        st.session_state["token"] = data["token"]
                        st.session_state["user"] = data["user"]
                        st.session_state["last_result"] = None  # fresh account, fresh page
                        st.rerun()
                    else:
                        st.error(resp.json().get("detail", "Sign up failed."))
                except Exception as exc:
                    st.error(f"Could not reach {API_BASE} ({exc}).")
    else:
        user = st.session_state["user"]
        st.markdown(f"**{user['email']}**")
        if user["is_paid"]:
            st.success("Unlimited plan ✅")
        else:
            st.metric("Free requests left", user["free_uses_remaining"])
            if user["free_uses_remaining"] <= 0:
                st.warning("Free limit reached.")
            if st.button("Upgrade (demo — no real charge)"):
                try:
                    resp = httpx.post(f"{API_BASE}/v1/auth/upgrade", headers=_auth_headers(), timeout=10)
                    if resp.status_code == 200:
                        st.session_state["user"] = resp.json()
                        st.rerun()
                    else:
                        st.error(resp.json().get("detail", "Upgrade failed."))
                except Exception as exc:
                    st.error(f"Could not reach {API_BASE} ({exc}).")

        # Same session, other view -- carries the token over so
        # dashboard.html opens already logged in as this account instead
        # of showing its own login form.
        st.link_button(
            "Open Agent Dispatch view ↗",
            f"{API_BASE}/dashboard?token={st.session_state['token']}",
        )
        st.caption(
            "Logging out below only ends the session here. To end it on the "
            "Agent Dispatch view too, "
            f"[click here]({API_BASE}/dashboard?logout=1) (opens in that page)."
        )
        if st.button("Log out"):
            st.session_state["token"] = None
            st.session_state["user"] = None
            st.session_state["last_result"] = None
            st.rerun()

if st.session_state["token"] is None:
    st.info("Log in or create a free account in the sidebar to use the router (5 free requests, no card needed).")
    st.stop()

# ---------------------------------------------------------------------------
# Stats / charts. Previously every account saw the same numbers here because
# these all hit the GLOBAL endpoints (/v1/stats, /v1/recent, ...), which
# aggregate every user's requests together. Default view is now each user's
# own data via the authenticated /me endpoints; the toggle below lets anyone
# switch back to the combined "everyone" view if they want it.
# ---------------------------------------------------------------------------
view_choice = st.radio("View", ["My usage", "Everyone (global demo)"], horizontal=True)
scope_me = view_choice == "My usage"
stats_path = "/v1/stats/me" if scope_me else "/v1/stats"
recent_path = "/v1/recent/me" if scope_me else "/v1/recent"
daily_path = "/v1/consumption/daily/me" if scope_me else "/v1/consumption/daily"
monthly_path = "/v1/consumption/monthly/me" if scope_me else "/v1/consumption/monthly"

try:
    stats = httpx.get(f"{API_BASE}{stats_path}", headers=_auth_headers(), timeout=5).json()
except Exception as exc:
    st.error(f"Could not reach the API at {API_BASE}. Is it running? ({exc})")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Requests", stats["total_requests"])
col2.metric("Estimated Savings", f"${stats['estimated_savings_usd']:.4f}", f"{stats['estimated_savings_pct']:.1f}%")
col3.metric("Total Cost", f"${stats['total_cost_usd']:.4f}")
col4.metric("Avg Latency", f"{stats['avg_latency_ms']:.0f} ms")

st.subheader("Route split")
split_df = pd.DataFrame(
    {"route": ["cheap", "frontier"], "requests": [stats["cheap_requests"], stats["frontier_requests"]]}
)
if split_df["requests"].sum() > 0:
    fig = px.pie(split_df, names="route", values="requests", hole=0.5,
                 color="route", color_discrete_map={"cheap": "#4FD1C5", "frontier": "#E8A33D"})
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No requests logged yet — send one below or via POST /v1/route.")

st.subheader("Available models")
try:
    models = httpx.get(f"{API_BASE}/v1/models", timeout=5).json()
except Exception as exc:
    st.warning(f"Could not load the model catalog from {API_BASE}/v1/models ({exc}). "
               "The model picker below will be empty until this is reachable.")
    models = []
models_df = pd.DataFrame(models)
st.dataframe(models_df, use_container_width=True, hide_index=True)

st.subheader("Consumption over time")
st.caption("Daily and monthly token usage and cost, per model. Filter by provider group "
           "(GPT / Gemini / other cloud models) or pick specific models.")

provider_options = ["gpt", "gemini", "cloud"]
provider_labels = {"gpt": "GPT models", "gemini": "Gemini", "cloud": "Other cloud / open-weight"}
selected_providers = st.multiselect(
    "Provider group", provider_options, default=provider_options,
    format_func=lambda p: provider_labels[p],
)
candidate_models = [m["name"] for m in models if m["provider"] in selected_providers]
selected_models = st.multiselect("Models to plot", candidate_models, default=candidate_models)

period_choice = st.radio("Granularity", ["Daily", "Monthly"], horizontal=True)

if selected_models:
    try:
        if period_choice == "Daily":
            resp = httpx.get(f"{API_BASE}{daily_path}", params={"days": 30}, headers=_auth_headers(), timeout=15)
        else:
            resp = httpx.get(f"{API_BASE}{monthly_path}", params={"months": 12}, headers=_auth_headers(), timeout=15)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        st.warning(
            f"Could not load consumption data from {API_BASE} ({exc}). "
            "If this app just woke up from being idle (Render's free tier spins down after inactivity), "
            "the first request can take 30-60s to cold-start and return something other than JSON in the "
            "meantime — wait a few seconds and click below to retry."
        )
        if st.button("Retry consumption data"):
            st.rerun()
        rows = []

    cons_df = pd.DataFrame(rows)
    if not cons_df.empty:
        cons_df = cons_df[cons_df["model_used"].isin(selected_models)]

    if cons_df.empty:
        st.info("No consumption logged yet for the selected models/period — send a few prompts below first.")
    else:
        tok_fig = px.line(
            cons_df, x="period", y="total_tokens", color="model_used", markers=True,
            title=f"{period_choice} token consumption by model",
            labels={"period": period_choice, "total_tokens": "Total tokens", "model_used": "Model"},
        )
        st.plotly_chart(tok_fig, use_container_width=True)

        cost_fig = px.line(
            cons_df, x="period", y="total_cost_usd", color="model_used", markers=True,
            title=f"{period_choice} cost (USD) by model",
            labels={"period": period_choice, "total_cost_usd": "Cost (USD)", "model_used": "Model"},
        )
        st.plotly_chart(cost_fig, use_container_width=True)
else:
    st.info("Select at least one model above to see its consumption trend.")

# ---------------------------------------------------------------------------
# Dispatch a prompt -- now a dedicated two-column layout: controls on the
# left, a persistent "Model Output" panel on the right. The result stays in
# st.session_state["last_result"] so the output column keeps showing the
# last response even as the rest of the page reruns (e.g. when you touch a
# filter above), instead of only flashing on screen for one run.
# ---------------------------------------------------------------------------
st.subheader("Dispatch a prompt")
left, right = st.columns([1, 1])

with left:
    prompt = st.text_area("Prompt", placeholder="Ask something simple, or something that needs multi-step reasoning...")

    col_a, col_b, col_c = st.columns(3)
    force = col_a.selectbox("Force route (optional)", ["auto", "cheap", "frontier"])
    model_choice = col_b.selectbox("Force model (optional)", ["default for route"] + [m["name"] for m in models])
    try:
        agents_catalog = httpx.get(f"{API_BASE}/v1/agents", timeout=5).json()
    except Exception:
        agents_catalog = []
    agent_choice = col_c.selectbox(
        "Force agent (optional)", ["auto-pick"] + [a["id"] for a in agents_catalog],
        format_func=lambda a: a if a == "auto-pick" else next((x["name"] for x in agents_catalog if x["id"] == a), a),
    )

    with st.expander("Run a real model (bring your own API key)"):
        st.caption(
            "Pick an OpenAI or Anthropic model above, paste the matching key here, and Send will call "
            "that model live instead of returning a mock reply. Keys are only used for this request — "
            "they are not saved to disk, not logged, and not stored in this browser session beyond the "
            "current page load."
        )
        key_col1, key_col2 = st.columns(2)
        anthropic_key = key_col1.text_input("Anthropic API key", type="password", placeholder="sk-ant-…")
        openai_key = key_col2.text_input("OpenAI API key", type="password", placeholder="sk-…")

    send_clicked = st.button("Send", type="primary")

    if send_clicked and prompt.strip():
        payload = {"prompt": prompt}
        if force != "auto":
            payload["force_route"] = force
        if model_choice != "default for route":
            payload["force_model"] = model_choice
        if agent_choice != "auto-pick":
            payload["force_agent"] = agent_choice
        if anthropic_key:
            payload["anthropic_api_key"] = anthropic_key
        if openai_key:
            payload["openai_api_key"] = openai_key

        try:
            resp = httpx.post(f"{API_BASE}/v1/route", json=payload, headers=_auth_headers(), timeout=60)
            if resp.status_code == 402:
                st.error(resp.json().get("detail", "Free limit reached."))
            elif resp.status_code == 401:
                st.session_state["token"] = None
                st.session_state["user"] = None
                st.error("Session expired — log in again.")
                st.rerun()
            elif resp.status_code != 200:
                st.error(f"API returned {resp.status_code}: {resp.text}")
            else:
                st.session_state["last_result"] = resp.json()
                # Refresh the free-uses counter shown in the sidebar.
                me_resp = httpx.get(f"{API_BASE}/v1/auth/me", headers=_auth_headers(), timeout=5)
                if me_resp.status_code == 200:
                    st.session_state["user"] = me_resp.json()
        except Exception as exc:
            st.error(f"Could not reach {API_BASE}/v1/route ({exc}). Is the API running?")

with right:
    st.markdown("#### Model Output")
    result = st.session_state.get("last_result")
    if result is None:
        st.info("Dispatch a prompt on the left to see the agent's response, tokens, and cost here.")
    else:
        live = result.get("is_live_call", False)
        badge = "🟢 LIVE" if live else "⚪ MOCK"
        st.markdown(
            f"**{badge}** &nbsp;|&nbsp; **Agent:** {result['agent_name']} ({result['agent_role']}) &nbsp;|&nbsp; "
            f"**Model used:** `{result['model_used']}` &nbsp;|&nbsp; **Route:** `{result['route']}`"
        )
        st.text_area("Response", result["response_text"], height=180, disabled=True, key="output_text_area")
        t1, t2, t3 = st.columns(3)
        t1.metric("Input tokens", result["input_tokens"])
        t2.metric("Output tokens", result["output_tokens"])
        t3.metric("Total tokens", result["total_tokens"])
        t4, t5 = st.columns(2)
        t4.metric("Total cost", f"${result['estimated_cost_usd']:.6f}")
        t5.metric("Latency (exact)", f"{result['latency_ms']} ms")
        st.caption(f"**Why this many tokens ({result['token_count_method']}):** {result['token_explanation']}")
        st.caption(f"**Why this route/model:** {result['routing_reason']}")
        st.caption(f"**Why this cost:** {result['cost_explanation']}")
        with st.expander("Full response JSON"):
            st.json(result)

st.subheader("Recent requests")
try:
    recent = httpx.get(f"{API_BASE}{recent_path}", headers=_auth_headers(), timeout=5).json()
except Exception as exc:
    st.warning(f"Could not load recent requests from {API_BASE}{recent_path} ({exc}).")
    recent = []
if recent:
    df = pd.DataFrame(recent)[
        ["ts", "route", "model_used", "complexity_score", "estimated_cost_usd", "latency_ms", "prompt_preview"]
    ]
    df["ts"] = pd.to_datetime(df["ts"], unit="s")
    st.dataframe(df, use_container_width=True)
else:
    st.info("Nothing logged yet.")
