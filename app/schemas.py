# Request/response models for the router API. Author: Midhul MS (Cryzal)
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RouteRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    force_route: Optional[Literal["cheap", "frontier"]] = None
    # Optional: pin a specific model instead of letting the router pick the
    # default for its tier, e.g. "gpt-4o-mini" instead of the frontier default.
    force_model: Optional[str] = None
    # Optional: pin a specific agent persona instead of letting pick_agent()
    # infer one from the prompt's complexity signals, e.g. "compiler".
    force_agent: Optional[str] = None

    # Optional bring-your-own-key for this single request, so a model can
    # run live from the dashboard without editing .env. Used only for the
    # outbound call in app/providers.py, never logged or stored.
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    # From https://huggingface.co/settings/tokens; runs any model tagged
    # api="huggingface" in MODEL_CATALOG.
    hf_api_key: Optional[str] = None


class RouteResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    route: Literal["cheap", "frontier"]
    model_used: str

    # which named agent persona handled this request (see app/agents.py)
    agent_id: str
    agent_name: str
    agent_role: str
    agent_tagline: str
    agent_description: str

    complexity_score: float
    response_text: str
    # True only when this reply came from a real provider-billed API call
    # (i.e. token_count_method == "provider-api-exact"). False for mock
    # replies and for local tiktoken/whitespace-counted fallbacks.
    is_live_call: bool

    input_tokens: int
    output_tokens: int
    total_tokens: int
    token_count_method: str           # "provider-api-exact" | "tiktoken-cl100k" | "whitespace-approx"
    token_explanation: str            # plain-English: how the token count was derived
    routing_reason: str               # plain-English: why this route/model was chosen

    estimated_cost_usd: float
    input_cost_usd: float
    output_cost_usd: float
    cost_explanation: str             # plain-English: why the cost came out this way

    latency_ms: int


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserInfo(BaseModel):
    id: int
    email: str
    free_uses_remaining: int
    is_paid: bool


class TokenResponse(BaseModel):
    token: str
    user: UserInfo


class ModelInfo(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str
    tier: Literal["cheap", "mid", "frontier"]
    provider: Literal["gpt", "gemini", "cloud"]
    # Backend app/providers.py::call_model() dispatches to for this model
    # ("anthropic" | "openai" | "mistral" | "gemini" | "huggingface" |
    # "ollama" | "mock"). Lets the dashboard show which key field a model
    # actually needs.
    api: str
    input_price_per_1k: float
    output_price_per_1k: float
    context_window: int


class AgentInfo(BaseModel):
    id: str
    name: str
    role: str
    icon: str
    accent: str
    tagline: str
    description: str


class StatsResponse(BaseModel):
    total_requests: int
    cheap_requests: int
    frontier_requests: int
    total_cost_usd: float
    baseline_cost_usd: float          # what it would have cost if every request went to frontier
    estimated_savings_usd: float
    estimated_savings_pct: float
    avg_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int


class AgentStat(BaseModel):
    agent_id: str
    agent_name: str
    requests: int
    total_tokens: int
    total_cost_usd: float
    avg_cost_usd: float


class ModelStat(BaseModel):
    model_used: str
    requests: int
    total_tokens: int
    total_cost_usd: float
    avg_cost_usd: float


class ConsumptionPoint(BaseModel):
    """One row per (period, model). 'period' is a day ('2026-07-03') for
    the daily series or a month ('2026-07') for the monthly series. This
    shape is what a line chart wants: group rows by model_used to get one
    line per model, with period on the x-axis."""
    model_config = ConfigDict(protected_namespaces=())

    period: str
    model_used: str
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost_usd: float
