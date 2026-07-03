# Prometheus metrics for the router. Author: Cryzal/midhul
#
# Same idea as the agentgateway FinOps setup (Prometheus scrapes a /metrics
# endpoint, Grafana charts it) but scoped to this single FastAPI app instead
# of a fleet of gateways -- so there's one exporter, not one per gateway.
#
# Four metrics cover everything the dashboard in that blog post showed:
#   - requests_total          -> "Total Daily Cost (All Gateways)" style counts
#   - tokens_total             -> "Total Input/Output Tokens"
#   - cost_usd_total           -> "Hourly/Weekly/Monthly Cost"
#   - request_latency_seconds  -> not in the blog's dashboard, added for free
#     since we're already timing every call.
#
# All four are labeled by route/model/agent so Grafana can break the same
# panel down "per Gateway" the way the reference dashboard does -- here
# that's "per model" / "per agent" instead of "per gateway".
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

requests_total = Counter(
    "router_requests_total",
    "Total requests handled by the router",
    ["route", "model", "agent"],
)

tokens_total = Counter(
    "router_tokens_total",
    "Total tokens processed",
    ["route", "model", "direction"],  # direction = input | output
)

cost_usd_total = Counter(
    "router_cost_usd_total",
    "Total estimated cost in USD",
    ["route", "model"],
)

baseline_cost_usd_total = Counter(
    "router_baseline_cost_usd_total",
    "Total cost in USD if every request had gone to the frontier model "
    "(the reference line for computing savings)",
    ["route", "model"],
)

request_latency_seconds = Histogram(
    "router_request_latency_seconds",
    "End-to-end latency per routed request",
    ["route", "model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)


def record(route: str, model: str, agent: str, input_tokens: int, output_tokens: int,
           cost_usd: float, baseline_cost_usd: float, latency_ms: int) -> None:
    """Single call site the router uses after every request -- keeps all the
    label logic in one place instead of scattered across router.py."""
    requests_total.labels(route=route, model=model, agent=agent).inc()
    tokens_total.labels(route=route, model=model, direction="input").inc(input_tokens)
    tokens_total.labels(route=route, model=model, direction="output").inc(output_tokens)
    cost_usd_total.labels(route=route, model=model).inc(cost_usd)
    baseline_cost_usd_total.labels(route=route, model=model).inc(baseline_cost_usd)
    request_latency_seconds.labels(route=route, model=model).observe(latency_ms / 1000)


def render() -> tuple[bytes, str]:
    """Returns (body, content_type) ready to hand straight to a FastAPI Response."""
    return generate_latest(), CONTENT_TYPE_LATEST
