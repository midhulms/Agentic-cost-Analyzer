# Agentic Cost Router API. Author: Midhul MS (Cryzal)
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.agents import all_agents
from app.auth import (
    consume_free_use, create_session, create_user,
    init_auth_db, mark_paid, require_user, verify_user,
)
from app.config import MODEL_CATALOG
from app.cost_tracker import (
    init_db, get_stats, get_recent, get_stats_by_agent, get_stats_by_model,
    get_daily_consumption, get_monthly_consumption,
)
from app.router import route_request
from app import metrics
from app.schemas import (
    RouteRequest, RouteResponse, StatsResponse, ModelInfo, AgentInfo, AgentStat, ModelStat,
    ConsumptionPoint, SignupRequest, LoginRequest, TokenResponse, UserInfo,
)

app = FastAPI(
    title="Agentic Cost Router",
    description="Routes prompts between a cheap open-weight model and a frontier model based on complexity, "
                 "tracks exact token counts and cost, and attributes every request to a named agent.",
    version="0.2.0",
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
    init_auth_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
def metrics_endpoint() -> Response:
    """Prometheus scrapes this. Format: text/plain in the standard exposition
    format. Point a Prometheus `scrape_configs` job at this path."""
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


@app.get("/dashboard")
def dashboard() -> FileResponse:
    """The humanized dashboard. A static page that talks to this same API."""
    return FileResponse(str(STATIC_DIR / "dashboard.html"))


@app.post("/v1/auth/signup", response_model=TokenResponse)
@limiter.limit("5/minute")
def signup(request: Request, req: SignupRequest) -> TokenResponse:
    """Create an account. Every new account starts with 5 free /v1/route
    calls before it needs to upgrade."""
    try:
        user = create_user(req.email, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    token = create_session(user["id"])
    return TokenResponse(token=token, user=UserInfo(**user))


@app.post("/v1/auth/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest) -> TokenResponse:
    user = verify_user(req.email, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    token = create_session(user["id"])
    return TokenResponse(token=token, user=UserInfo(**user))


@app.get("/v1/auth/me", response_model=UserInfo)
def me(user: dict = Depends(require_user)) -> UserInfo:
    """Lets a client (dashboard.py, dashboard.html) check remaining free
    uses / paid status for whichever token it's holding."""
    return UserInfo(**user)


@app.post("/v1/auth/upgrade", response_model=UserInfo)
def upgrade(user: dict = Depends(require_user)) -> UserInfo:
    """MOCK upgrade. Flips the account to unlimited with no real charge.
    Replace the body of this endpoint with a Stripe Checkout session
    creation, and flip is_paid from a Stripe webhook instead, before
    taking this live with real payments."""
    updated = mark_paid(user["id"])
    return UserInfo(**updated)


@app.post("/v1/route", response_model=RouteResponse)
@limiter.limit("100/minute")
def route(request: Request, req: RouteRequest, user: dict = Depends(require_user)) -> RouteResponse:
    quota = consume_free_use(user["id"])
    if not quota["allowed"]:
        raise HTTPException(
            status_code=402,
            detail="Free limit reached (5 requests). Call POST /v1/auth/upgrade to continue "
                   "(mock upgrade for this demo. Wire up real billing before charging anyone).",
        )
    return route_request(req, user_id=user["id"])


@app.get("/v1/stats", response_model=StatsResponse)
def stats() -> StatsResponse:
    """GLOBAL aggregate across every user. The public 'leaderboard' view.
    For an individual user's own numbers, see /v1/stats/me instead."""
    return StatsResponse(**get_stats())


@app.get("/v1/stats/me", response_model=StatsResponse)
def stats_me(user: dict = Depends(require_user)) -> StatsResponse:
    """Same shape as /v1/stats, filtered to only the logged-in user's own
    requests. This is what fixes 'every user shows the same usage'."""
    return StatsResponse(**get_stats(user_id=user["id"]))


@app.get("/v1/stats/agents", response_model=list[AgentStat])
def stats_by_agent() -> list[AgentStat]:
    return [AgentStat(**row) for row in get_stats_by_agent()]


@app.get("/v1/stats/agents/me", response_model=list[AgentStat])
def stats_by_agent_me(user: dict = Depends(require_user)) -> list[AgentStat]:
    return [AgentStat(**row) for row in get_stats_by_agent(user_id=user["id"])]


@app.get("/v1/stats/models", response_model=list[ModelStat])
def stats_by_model() -> list[ModelStat]:
    return [ModelStat(**row) for row in get_stats_by_model()]


@app.get("/v1/stats/models/me", response_model=list[ModelStat])
def stats_by_model_me(user: dict = Depends(require_user)) -> list[ModelStat]:
    return [ModelStat(**row) for row in get_stats_by_model(user_id=user["id"])]


@app.get("/v1/recent")
def recent(limit: int = 25) -> list:
    return get_recent(limit)


@app.get("/v1/recent/me")
def recent_me(limit: int = 25, user: dict = Depends(require_user)) -> list:
    return get_recent(limit, user_id=user["id"])


@app.get("/v1/models", response_model=list[ModelInfo])
def models() -> list[ModelInfo]:
    """Every model the router can pick between, with pricing and context window,
    so a client (or the dashboard) can offer them as alternatives to force_model."""
    return [
        ModelInfo(
            name=name,
            tier=info["tier"],
            provider=info["provider"],
            api=info["api"],
            input_price_per_1k=info["input"],
            output_price_per_1k=info["output"],
            context_window=info["context_window"],
        )
        for name, info in MODEL_CATALOG.items()
    ]


@app.get("/v1/consumption/daily", response_model=list[ConsumptionPoint])
def consumption_daily(days: int = 30, model: str | None = None) -> list[ConsumptionPoint]:
    """One point per (day, model) for the last `days` days. Feeds the daily
    line graph. Filter to one model with ?model=gpt-4o, or omit it to get
    every model's series back at once (group by model_used client-side)."""
    return [ConsumptionPoint(**row) for row in get_daily_consumption(days=days, model=model)]


@app.get("/v1/consumption/daily/me", response_model=list[ConsumptionPoint])
def consumption_daily_me(days: int = 30, model: str | None = None, user: dict = Depends(require_user)) -> list[ConsumptionPoint]:
    return [ConsumptionPoint(**row) for row in get_daily_consumption(days=days, model=model, user_id=user["id"])]


@app.get("/v1/consumption/monthly", response_model=list[ConsumptionPoint])
def consumption_monthly(months: int = 12, model: str | None = None) -> list[ConsumptionPoint]:
    """Same shape as /v1/consumption/daily, bucketed by calendar month."""
    return [ConsumptionPoint(**row) for row in get_monthly_consumption(months=months, model=model)]


@app.get("/v1/consumption/monthly/me", response_model=list[ConsumptionPoint])
def consumption_monthly_me(months: int = 12, model: str | None = None, user: dict = Depends(require_user)) -> list[ConsumptionPoint]:
    return [ConsumptionPoint(**row) for row in get_monthly_consumption(months=months, model=model, user_id=user["id"])]


@app.get("/v1/agents", response_model=list[AgentInfo])
def agents() -> list[AgentInfo]:
    """Every named agent persona the router can attribute a request to."""
    return [AgentInfo(**a) for a in all_agents()]
