# Routing logic: picks a model tier by prompt complexity, hands it to an
# agent persona, calls the model, and logs token/cost data. Author: Cryzal
from app.agents import agent_info, pick_agent
from app.complexity import score_with_explanation
from app.config import settings, price_for, api_for
from app.providers import call_model, timed_call, explain_tokens, explain_cost
from app.cost_tracker import log_request
from app import metrics
from app.schemas import RouteRequest, RouteResponse


def _cost_breakdown(model_name: str, input_tokens: int, output_tokens: int) -> dict:
    prices = price_for(model_name)
    input_cost = (input_tokens / 1000) * prices["input"]
    output_cost = (output_tokens / 1000) * prices["output"]
    return {
        "input_price_per_1k": prices["input"],
        "output_price_per_1k": prices["output"],
        "input_cost_usd": input_cost,
        "output_cost_usd": output_cost,
        "total_cost_usd": input_cost + output_cost,
    }


def route_request(req: RouteRequest, user_id: int | None = None) -> RouteResponse:
    breakdown = score_with_explanation(req.prompt)
    complexity = breakdown["score"]

    if req.force_route:
        route = req.force_route
        routing_reason = f"Manually forced to '{route}' (ignoring complexity score {complexity})."
    else:
        route = "frontier" if complexity >= settings.complexity_threshold else "cheap"
        routing_reason = (
            f"{breakdown['reason']} Complexity score {complexity} "
            f"{'>=' if route == 'frontier' else '<'} threshold {settings.complexity_threshold}, "
            f"so routed to '{route}'."
        )

    if req.force_agent:
        agent = agent_info(req.force_agent)
        agent_key = agent["id"]
        if agent_key == req.force_agent:
            routing_reason += f" Agent manually forced to '{agent['name']}' (ignoring auto-picked persona)."
        else:
            routing_reason += (
                f" force_agent='{req.force_agent}' isn't a known agent, fell back to '{agent['name']}'."
            )
    else:
        agent_key = pick_agent(breakdown["signals"], route, req.prompt)
        agent = agent_info(agent_key)

    if route == "cheap":
        default_model = settings.cheap_model_name if settings.cheap_provider != "mock" else "mock-cheap"
    else:
        default_model = settings.frontier_model_name if settings.frontier_provider != "mock" else "mock-frontier"
    model_used = req.force_model or default_model

    # One dispatch point for every model: providers.call_model() looks up
    # which real API model_used belongs to and calls it live if a key is
    # available (from this request or from .env); otherwise it returns a
    # clearly-labeled mock reply. This is what makes picking a specific
    # model in the dashboard (e.g. gpt-4o, claude-sonnet-5) actually run
    # that model instead of just relabeling a generic mock response.
    text, in_tok, out_tok, method, latency_ms = timed_call(
        lambda p, m: call_model(p, m, anthropic_key=req.anthropic_api_key, openai_key=req.openai_api_key),
        req.prompt, model_used,
    )
    # "provider-api-exact" covers OpenAI/Anthropic/Mistral, which report
    # billed usage directly. Ollama never reports usage (so its method is
    # tiktoken/whitespace even on a real call) -- for that one case, treat
    # anything that isn't one of providers.py's own bracketed
    # mock/failure/not-configured messages as a genuine live reply.
    is_live_call = method == "provider-api-exact" or (
        api_for(model_used) == "ollama" and not text.startswith("[")
    )

    total_tokens = in_tok + out_tok
    token_explanation = explain_tokens(req.prompt, in_tok, out_tok, method=method)

    cost = _cost_breakdown(model_used, in_tok, out_tok)
    cost_explanation = explain_cost(
        model_used, in_tok, out_tok,
        cost["input_price_per_1k"], cost["output_price_per_1k"],
        cost["input_cost_usd"], cost["output_cost_usd"], cost["total_cost_usd"],
        route,
    )

    # baseline = what this same request would have cost on the frontier model,
    # so the dashboard can show real savings even when routed cheap.
    frontier_model_name = settings.frontier_model_name if settings.frontier_provider != "mock" else "mock-frontier"
    baseline_cost = _cost_breakdown(frontier_model_name, in_tok, out_tok)["total_cost_usd"]

    log_request(
        route=route,
        model_used=model_used,
        agent_id=agent["id"],
        agent_name=agent["name"],
        complexity_score=complexity,
        input_tokens=in_tok,
        output_tokens=out_tok,
        token_count_method=method,
        estimated_cost_usd=cost["total_cost_usd"],
        baseline_cost_usd=baseline_cost,
        latency_ms=latency_ms,
        prompt=req.prompt,
        user_id=user_id,
    )

    # Same numbers just logged to SQLite, also pushed to Prometheus so
    # Grafana (or `curl /metrics`) can see them in near real time.
    metrics.record(
        route=route,
        model=model_used,
        agent=agent["id"],
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost["total_cost_usd"],
        baseline_cost_usd=baseline_cost,
        latency_ms=latency_ms,
    )

    return RouteResponse(
        route=route,
        model_used=model_used,
        agent_id=agent["id"],
        agent_name=agent["name"],
        agent_role=agent["role"],
        agent_tagline=agent["tagline"],
        agent_description=agent["description"],
        complexity_score=complexity,
        response_text=text,
        is_live_call=is_live_call,
        input_tokens=in_tok,
        output_tokens=out_tok,
        total_tokens=total_tokens,
        token_count_method=method,
        token_explanation=token_explanation,
        routing_reason=routing_reason,
        estimated_cost_usd=round(cost["total_cost_usd"], 6),
        input_cost_usd=round(cost["input_cost_usd"], 6),
        output_cost_usd=round(cost["output_cost_usd"], 6),
        cost_explanation=cost_explanation,
        latency_ms=latency_ms,
    )
