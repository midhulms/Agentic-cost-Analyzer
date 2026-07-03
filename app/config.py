"""
Central configuration for the router.

Author: midhul/Cryzal

Everything here is overridable via environment variables (see .env.example),
so the same code runs in "mock" mode with no API keys for local demos,
and in "live" mode once real provider credentials are supplied.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- routing ---
    # 0.0-1.0. Prompts scoring below this go to the cheap model.
    complexity_threshold: float = 0.55

    # --- cheap / open-weight path ---
    cheap_provider: str = "mock"          # "mock" | "ollama" | "mistral"
    cheap_model_name: str = "llama3.1:8b"
    ollama_base_url: str = "http://localhost:11434"
    mistral_api_key: str = ""

    # --- frontier path ---
    frontier_provider: str = "mock"       # "mock" | "anthropic" | "openai"
    frontier_model_name: str = "claude-sonnet-5"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # --- storage ---
    # Relative to the app's working directory (/app in Docker). Deliberately
    # under "data/" so it lines up with the ./data volume mount in
    # docker-compose.yml (local persistence) and with a Render persistent
    # disk mounted at /app/data, if one is attached (see render.yaml).
    # IMPORTANT: Render's FREE tier has no persistent disk -- the container
    # filesystem is wiped on every deploy and on every cold-start after the
    # service spins down from inactivity. On free tier this data will
    # periodically reset to zero; that's expected, not a bug. Attach a paid
    # persistent disk (or point db_path at an external DB) to keep it.
    db_path: str = "data/cost_router.db"


settings = Settings()

# Model catalog: every model the router is allowed to pick between, grouped
# by tier. "tier" is what the router logic keys off; "provider" groups
# models the way a model-selection dropdown would (GPT / cloud / Gemini);
# "api" tells providers.call_model() which real backend to hit when a key
# is available ("anthropic" | "openai" | "mistral" | "ollama" | "gemini" |
# "mock") -- this is what makes picking a model in the dashboard actually
# call that model's real API instead of just relabeling a mock reply;
# "input"/"output" are rough reference USD per 1K tokens (for estimated
# cost, not billing); "context_window" is included so the dashboard can
# warn if a prompt is too long for a given model.
MODEL_CATALOG = {
    # --- cheap / open-weight tier ---
    "llama3.1:8b":     {"tier": "cheap",    "provider": "cloud",    "api": "ollama", "input": 0.0002, "output": 0.0002, "context_window": 128_000},
    "mistral-7b":       {"tier": "cheap",    "provider": "cloud",    "api": "ollama", "input": 0.00025, "output": 0.00025, "context_window": 32_000},
    "mock-cheap":       {"tier": "cheap",    "provider": "cloud",    "api": "mock",   "input": 0.0002, "output": 0.0002, "context_window": 128_000},

    # --- real hosted "cheap" models (need an API key, see .env.example) ---
    "mistral-small-latest": {"tier": "cheap", "provider": "cloud",   "api": "mistral", "input": 0.0002, "output": 0.0006, "context_window": 32_000},
    "gpt-3.5-turbo":         {"tier": "cheap", "provider": "gpt",    "api": "openai",  "input": 0.0005, "output": 0.0015, "context_window": 16_000},

    # --- mid tier (optional middle ground between cheap and frontier) ---
    "claude-haiku-4-5": {"tier": "mid",      "provider": "cloud",    "api": "anthropic", "input": 0.001,  "output": 0.005,  "context_window": 200_000},
    "gpt-4o-mini":      {"tier": "mid",      "provider": "gpt",      "api": "openai",    "input": 0.00015, "output": 0.0006, "context_window": 128_000},
    "mistral-large-latest": {"tier": "mid",  "provider": "cloud",    "api": "mistral",   "input": 0.002,  "output": 0.006,  "context_window": 128_000},
    "gemini-1.5-flash": {"tier": "mid",      "provider": "gemini",   "api": "gemini",    "input": 0.000075, "output": 0.0003, "context_window": 1_000_000},

    # --- frontier tier ---
    "claude-sonnet-5":  {"tier": "frontier", "provider": "cloud",    "api": "anthropic", "input": 0.003,  "output": 0.015,  "context_window": 200_000},
    "gpt-4o":           {"tier": "frontier", "provider": "gpt",      "api": "openai",    "input": 0.0025, "output": 0.01,   "context_window": 128_000},
    "gemini-1.5-pro":   {"tier": "frontier", "provider": "gemini",   "api": "gemini",    "input": 0.00125, "output": 0.005,  "context_window": 2_000_000},
    "mock-frontier":    {"tier": "frontier", "provider": "cloud",    "api": "mock",      "input": 0.003,  "output": 0.015,  "context_window": 200_000},
}


def price_for(model_name: str) -> dict:
    entry = MODEL_CATALOG.get(model_name, {"input": 0.003, "output": 0.015})
    return {"input": entry["input"], "output": entry["output"]}


def api_for(model_name: str) -> str:
    """Which real backend a model name should be dispatched to. Falls back
    to 'mock' for anything not in the catalog (e.g. a typo'd force_model)."""
    return MODEL_CATALOG.get(model_name, {}).get("api", "mock")


def models_by_tier(tier: str) -> list[str]:
    return [name for name, info in MODEL_CATALOG.items() if info["tier"] == tier]


def models_by_provider(provider: str) -> list[str]:
    return [name for name, info in MODEL_CATALOG.items() if info["provider"] == provider]
