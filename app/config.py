"""
Central configuration for the router.

Author: Midhul MS (Cryzal)

Everything here is overridable via environment variables (see .env.example),
so the same code runs in "mock" mode with no API keys for local demos,
and in "live" mode once real provider credentials are supplied.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Routing
    # 0.0-1.0. Prompts scoring below this go to the cheap model.
    complexity_threshold: float = 0.55

    # Cheap / open-weight path
    cheap_provider: str = "mock"          # "mock" | "ollama" | "mistral"
    cheap_model_name: str = "llama3.1:8b"
    ollama_base_url: str = "http://localhost:11434"
    mistral_api_key: str = ""
    gemini_api_key: str = ""

    # Frontier path
    frontier_provider: str = "mock"       # "mock" | "anthropic" | "openai"
    frontier_model_name: str = "claude-sonnet-5"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Hugging Face Inference Providers (free tier available).
    # Token from https://huggingface.co/settings/tokens, works across every
    # model in MODEL_CATALOG with api="huggingface".
    hf_api_key: str = ""

    # Storage path, relative to the app's working directory (/app in Docker).
    # Matches the ./data volume in docker-compose.yml and a Render disk at
    # /app/data if one is attached. Render's free tier has no persistent
    # disk, so data resets on redeploy/cold-start there unless upgraded.
    db_path: str = "data/cost_router.db"


settings = Settings()

# Model catalog: every model the router can pick between, grouped by tier.
# "tier" drives the routing logic; "provider" groups models for the
# dashboard dropdown; "api" tells providers.call_model() which backend to
# hit; "input"/"output" are reference USD per 1K tokens for cost estimates;
# "context_window" lets the dashboard warn on oversized prompts.
MODEL_CATALOG = {
    # Cheap / open-weight tier
    "llama3.1:8b":     {"tier": "cheap",    "provider": "cloud",    "api": "ollama", "input": 0.0002, "output": 0.0002, "context_window": 128_000},
    "mistral-7b":       {"tier": "cheap",    "provider": "cloud",    "api": "ollama", "input": 0.00025, "output": 0.00025, "context_window": 32_000},
    "mock-cheap":       {"tier": "cheap",    "provider": "cloud",    "api": "mock",   "input": 0.0002, "output": 0.0002, "context_window": 128_000},

    # Real hosted "cheap" models (need an API key, see .env.example)
    "mistral-small-latest": {"tier": "cheap", "provider": "cloud",   "api": "mistral", "input": 0.0002, "output": 0.0006, "context_window": 32_000},
    "gpt-3.5-turbo":         {"tier": "cheap", "provider": "gpt",    "api": "openai",  "input": 0.0005, "output": 0.0015, "context_window": 16_000},

    # Mid tier (optional middle ground between cheap and frontier)
    "claude-haiku-4-5": {"tier": "mid",      "provider": "cloud",    "api": "anthropic", "input": 0.001,  "output": 0.005,  "context_window": 200_000},
    "gpt-4o-mini":      {"tier": "mid",      "provider": "gpt",      "api": "openai",    "input": 0.00015, "output": 0.0006, "context_window": 128_000},
    "mistral-large-latest": {"tier": "mid",  "provider": "cloud",    "api": "mistral",   "input": 0.002,  "output": 0.006,  "context_window": 128_000},
    "gemini-1.5-flash": {"tier": "mid",      "provider": "gemini",   "api": "gemini",    "input": 0.000075, "output": 0.0003, "context_window": 1_000_000},

    # Frontier tier
    "claude-sonnet-5":  {"tier": "frontier", "provider": "cloud",    "api": "anthropic", "input": 0.003,  "output": 0.015,  "context_window": 200_000},
    "gpt-4o":           {"tier": "frontier", "provider": "gpt",      "api": "openai",    "input": 0.0025, "output": 0.01,   "context_window": 128_000},
    "gemini-1.5-pro":   {"tier": "frontier", "provider": "gemini",   "api": "gemini",    "input": 0.00125, "output": 0.005,  "context_window": 2_000_000},
    "mock-frontier":    {"tier": "frontier", "provider": "cloud",    "api": "mock",      "input": 0.003,  "output": 0.015,  "context_window": 200_000},

    # Hugging Face Inference Providers. One free token runs all of these
    # (https://huggingface.co/settings/tokens); prices shown are the
    # underlying backend provider's per-1K rate, passed through by HF.
    "meta-llama/Llama-3.1-8B-Instruct":  {"tier": "cheap",    "provider": "cloud", "api": "huggingface", "input": 0.00005, "output": 0.00008, "context_window": 128_000},
    "Qwen/Qwen2.5-72B-Instruct":         {"tier": "mid",      "provider": "cloud", "api": "huggingface", "input": 0.0004,  "output": 0.0004,  "context_window": 32_000},
    "meta-llama/Llama-3.3-70B-Instruct": {"tier": "mid",      "provider": "cloud", "api": "huggingface", "input": 0.0004,  "output": 0.0004,  "context_window": 128_000},
    "deepseek-ai/DeepSeek-V3-0324":      {"tier": "frontier", "provider": "cloud", "api": "huggingface", "input": 0.00027, "output": 0.0011,  "context_window": 64_000},
    "openai/gpt-oss-120b":               {"tier": "frontier", "provider": "cloud", "api": "huggingface", "input": 0.00015, "output": 0.0006,  "context_window": 128_000},
    "moonshotai/Kimi-K2-Instruct-0905":  {"tier": "frontier", "provider": "cloud", "api": "huggingface", "input": 0.00055, "output": 0.0022,  "context_window": 262_000},
    # Z.ai's flagship model on HF Inference Providers; the ":zai-org" suffix
    # pins routing to Z.ai's own backend instead of HF's default picker.
    "zai-org/GLM-5.2:zai-org":           {"tier": "frontier", "provider": "cloud", "api": "huggingface", "input": 0.0006,  "output": 0.0022,  "context_window": 1_000_000},
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
