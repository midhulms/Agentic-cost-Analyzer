import os

os.environ.setdefault("DB_PATH", "test_cost_router.db")

from app.router import route_request  # noqa: E402
from app.schemas import RouteRequest  # noqa: E402
from app.cost_tracker import init_db  # noqa: E402


def setup_module(_module):
    init_db()


def test_route_forced_cheap():
    resp = route_request(RouteRequest(prompt="Hello there", force_route="cheap"))
    assert resp.route == "cheap"
    assert resp.estimated_cost_usd >= 0


def test_route_forced_frontier():
    resp = route_request(RouteRequest(prompt="Hello there", force_route="frontier"))
    assert resp.route == "frontier"


def test_route_auto_picks_something():
    resp = route_request(RouteRequest(prompt="What's the weather like on Mars?"))
    assert resp.route in ("cheap", "frontier")


def test_response_includes_token_breakdown_and_reasons():
    resp = route_request(RouteRequest(prompt="Hello there"))
    assert resp.total_tokens == resp.input_tokens + resp.output_tokens
    assert resp.token_explanation  # non-empty
    assert resp.routing_reason  # non-empty


def test_force_model_overrides_default():
    resp = route_request(
        RouteRequest(prompt="quick question", force_route="frontier", force_model="gpt-4o")
    )
    assert resp.model_used == "gpt-4o"


def test_response_includes_agent_and_cost_breakdown():
    resp = route_request(RouteRequest(prompt="Hello there"))
    assert resp.agent_id
    assert resp.agent_name
    assert resp.cost_explanation
    assert round(resp.input_cost_usd + resp.output_cost_usd, 6) == resp.estimated_cost_usd
    assert resp.token_count_method in ("provider-api-exact", "tiktoken-cl100k", "whitespace-approx")


def test_code_prompt_routes_to_compiler_agent():
    resp = route_request(RouteRequest(prompt="Why does this fail?\n```def f(x): return x/0```"))
    assert resp.agent_id == "compiler"


def test_planning_prompt_routes_to_atlas_agent():
    resp = route_request(
        RouteRequest(prompt="Give me a step by step plan: first, set up the repo, then write tests, finally deploy.")
    )
    assert resp.agent_id == "atlas"


def test_summarize_prompt_routes_to_echo_agent():
    resp = route_request(RouteRequest(prompt="Can you summarize this article for me?"))
    assert resp.agent_id == "echo"


def test_force_agent_overrides_auto_pick():
    # "resume make" has no code/planning/reasoning signals, so it would
    # normally land on Sparrow. Force_agent should override that.
    resp = route_request(RouteRequest(prompt="resume make", force_agent="compiler"))
    assert resp.agent_id == "compiler"
    assert resp.agent_name == "Compiler"
    assert "forced" in resp.routing_reason.lower()


def test_force_agent_unknown_key_falls_back_to_sparrow():
    resp = route_request(RouteRequest(prompt="hi", force_agent="not-a-real-agent"))
    assert resp.agent_id == "sparrow"
    assert resp.agent_name == "Sparrow"
    assert "not-a-real-agent" in resp.routing_reason


def test_mock_dispatch_is_not_live():
    resp = route_request(RouteRequest(prompt="hi", force_route="frontier", force_model="gpt-4o"))
    assert resp.is_live_call is False
    assert "no OpenAI API key configured" in resp.response_text


def test_bad_key_attempts_real_call_and_reports_failure():
    # A per-request key should make the router actually try the real
    # OpenAI API (not just mock). An invalid key should come back as a
    # clearly-labeled failure, not a silent mock relabel, and should still
    # never crash the request.
    resp = route_request(
        RouteRequest(
            prompt="hi", force_route="frontier", force_model="gpt-4o",
            openai_api_key="sk-definitely-not-a-real-key",
        )
    )
    assert resp.is_live_call is False
    assert "openai call failed" in resp.response_text.lower()
    assert resp.estimated_cost_usd >= 0
