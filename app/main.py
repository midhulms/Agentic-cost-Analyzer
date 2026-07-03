# Agentic Cost Router API. Author: Cryzal/midhul
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents import all_agents
from app.config import MODEL_CATALOG
from app.cost_tracker import (
    init_db, get_stats, get_recent, get_stats_by_agent, get_stats_by_model,
    get_daily_consumption, get_monthly_consumption,
)
from app.router import route_request
from app import metrics
from app.schemas import (
    RouteRequest, RouteResponse, StatsResponse, ModelInfo, AgentInfo, AgentStat, ModelStat,
    ConsumptionPoint,
)

app = FastAPI(
    title="Agentic Cost Router",
    description="Routes prompts between a cheap open-weight model and a frontier model based on complexity, "
                 "tracks exact token counts and cost, and attributes every request to a named agent.",
    version="0.2.0",
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
def metrics_endpoint() -> Response:
    """Prometheus scrapes this. Format: text/plain in the standard exposition
    format -- point a Prometheus `scrape_configs` job at this path."""
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


@app.get("/dashboard")
def dashboard() -> FileResponse:
    """The humanized dashboard -- a static page that talks to this same API."""
    return FileResponse(str(STATIC_DIR / "dashboard.html"))


@app.post("/v1/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    return route_request(req)


@app.get("/v1/stats", response_model=StatsResponse)
def stats() -> StatsResponse:
    return StatsResponse(**get_stats())


@app.get("/v1/stats/agents", response_model=list[AgentStat])
def stats_by_agent() -> list[AgentStat]:
    return [AgentStat(**row) for row in get_stats_by_agent()]


@app.get("/v1/stats/models", response_model=list[ModelStat])
def stats_by_model() -> list[ModelStat]:
    return [ModelStat(**row) for row in get_stats_by_model()]


@app.get("/v1/recent")
def recent(limit: int = 25) -> list:
    return get_recent(limit)


@app.get("/v1/models", response_model=list[ModelInfo])
def models() -> list[ModelInfo]:
    """Every model the router can pick between, with pricing and context window,
    so a client (or the dashboard) can offer them as alternatives to force_model."""
    return [
        ModelInfo(
            name=name,
            tier=info["tier"],
            provider=info["provider"],
            input_price_per_1k=info["input"],
            output_price_per_1k=info["output"],
            context_window=info["context_window"],
        )
        for name, info in MODEL_CATALOG.items()
    ]


@app.get("/v1/consumption/daily", response_model=list[ConsumptionPoint])
def consumption_daily(days: int = 30, model: str | None = None) -> list[ConsumptionPoint]:
    """One point per (day, model) for the last `days` days. Feeds the daily
    line graph -- filter to one model with ?model=gpt-4o, or omit it to get
    every model's series back at once (group by model_used client-side)."""
    return [ConsumptionPoint(**row) for row in get_daily_consumption(days=days, model=model)]


@app.get("/v1/consumption/monthly", response_model=list[ConsumptionPoint])
def consumption_monthly(months: int = 12, model: str | None = None) -> list[ConsumptionPoint]:
    """Same shape as /v1/consumption/daily, bucketed by calendar month."""
    return [ConsumptionPoint(**row) for row in get_monthly_consumption(months=months, model=model)]


@app.get("/v1/agents", response_model=list[AgentInfo])
def agents() -> list[AgentInfo]:
    """Every named agent persona the router can attribute a request to."""
    return [AgentInfo(**a) for a in all_agents()]
