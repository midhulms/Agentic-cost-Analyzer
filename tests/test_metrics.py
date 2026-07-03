import os

os.environ.setdefault("DB_PATH", "test_cost_router.db")

from app.router import route_request  # noqa: E402
from app.schemas import RouteRequest  # noqa: E402
from app.cost_tracker import init_db  # noqa: E402
from app import metrics  # noqa: E402


def setup_module(_module):
    init_db()


def test_metrics_render_returns_prometheus_text_format():
    body, content_type = metrics.render()
    assert b"router_requests_total" in body
    assert "text/plain" in content_type


def test_routing_a_request_increments_metrics():
    before = metrics.requests_total.labels(route="cheap", model="mock-cheap", agent="sparrow")._value.get()
    route_request(RouteRequest(prompt="hi", force_route="cheap", force_model="mock-cheap"))
    after = metrics.requests_total.labels(route="cheap", model="mock-cheap", agent="sparrow")._value.get()
    assert after == before + 1


def test_daily_consumption_reflects_a_routed_request():
    from app.cost_tracker import get_daily_consumption

    route_request(RouteRequest(prompt="quick check", force_route="cheap", force_model="gemini-1.5-flash"))
    rows = get_daily_consumption(days=1, model="gemini-1.5-flash")
    assert len(rows) >= 1
    assert rows[-1]["model_used"] == "gemini-1.5-flash"
    assert rows[-1]["total_tokens"] > 0


def test_monthly_consumption_reflects_a_routed_request():
    from app.cost_tracker import get_monthly_consumption

    route_request(RouteRequest(prompt="quick check", force_route="frontier", force_model="gpt-4o"))
    rows = get_monthly_consumption(months=1, model="gpt-4o")
    assert len(rows) >= 1
    assert rows[-1]["model_used"] == "gpt-4o"
    assert rows[-1]["total_cost_usd"] > 0
