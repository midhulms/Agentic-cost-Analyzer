# Streamlit dashboard for the Agentic Cost Router. Author: Cryzal/midhul
import os
import httpx
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Agentic Cost Router", layout="wide")

import os
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
        f"(e.g. {API_BASE}/dashboard) — cards per agent, a printed cost ticket per prompt, and charts.")

try:
    stats = httpx.get(f"{API_BASE}/v1/stats", timeout=5).json()
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
    if period_choice == "Daily":
        rows = httpx.get(f"{API_BASE}/v1/consumption/daily", params={"days": 30}, timeout=10).json()
    else:
        rows = httpx.get(f"{API_BASE}/v1/consumption/monthly", params={"months": 12}, timeout=10).json()

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

st.subheader("Try a prompt")
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

if st.button("Send") and prompt.strip():
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
        result = httpx.post(f"{API_BASE}/v1/route", json=payload, timeout=60).json()
    except Exception as exc:
        st.error(f"Could not reach {API_BASE}/v1/route ({exc}). Is the API running?")
        result = None

    if result is not None:
        live = result.get("is_live_call", False)
        badge = "🟢 LIVE" if live else "⚪ MOCK"
        st.markdown(
            f"**{badge}** &nbsp;|&nbsp; **Agent:** {result['agent_name']} ({result['agent_role']}) &nbsp;|&nbsp; "
            f"**Model used:** `{result['model_used']}` &nbsp;|&nbsp; **Route:** `{result['route']}`"
        )
        st.text_area("Response", result["response_text"], height=140, disabled=True)
        t1, t2, t3, t4, t5 = st.columns(5)
        t1.metric("Input tokens", result["input_tokens"])
        t2.metric("Output tokens", result["output_tokens"])
        t3.metric("Total tokens", result["total_tokens"])
        t4.metric("Total cost", f"${result['estimated_cost_usd']:.6f}")
        t5.metric("Latency (exact)", f"{result['latency_ms']} ms")
        st.caption(f"**Why this many tokens ({result['token_count_method']}):** {result['token_explanation']}")
        st.caption(f"**Why this route/model:** {result['routing_reason']}")
        st.caption(f"**Why this cost:** {result['cost_explanation']}")
        with st.expander("Full response JSON"):
            st.json(result)
        # No st.rerun() here on purpose: Streamlit already reruns this
        # script on every button click, and that single rerun is the one
        # that has to carry this result to the browser. An extra manual
        # rerun() immediately after would restart the script *again* --
        # on that second pass st.button("Send") is False (nothing was
        # clicked to trigger it), so the whole block above never runs and
        # the result the user just generated is thrown away before it's
        # ever rendered. The "Recent requests" table below still refreshes
        # in this same run, since it's fetched fresh every time.

st.subheader("Recent requests")
try:
    recent = httpx.get(f"{API_BASE}/v1/recent", timeout=5).json()
except Exception as exc:
    st.warning(f"Could not load recent requests from {API_BASE}/v1/recent ({exc}).")
    recent = []
if recent:
    df = pd.DataFrame(recent)[
        ["ts", "route", "model_used", "complexity_score", "estimated_cost_usd", "latency_ms", "prompt_preview"]
    ]
    df["ts"] = pd.to_datetime(df["ts"], unit="s")
    st.dataframe(df, use_container_width=True)
else:
    st.info("Nothing logged yet.")
