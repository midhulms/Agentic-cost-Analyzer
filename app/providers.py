"""
Thin adapters around each backend so app/router.py never has to know
whether it's talking to a local Ollama model, a hosted API, or a mock.

Author: Cryzal & Midhul

Every call_* function returns (text, input_tokens, output_tokens, count_method).

Token counting, in order of preference:
1. Provider-reported usage (Anthropic API). Exact, comes straight from billing.
2. tiktoken cl100k_base encoding. Exact tokenization, run 100% locally,
   no API key or network call required. It's the same encoding family
   OpenAI's GPT-3.5/GPT-4 models use, and it's a free/open-source library
   (pip install tiktoken), which is why it's used here as the default
   "real" counter instead of a word-count guess. It won't match every
   model's tokenizer byte-for-byte (Llama, Mistral, Claude all use their
   own vocabularies), but it is an exact count of *something real* rather
   than an approximation, and it's close enough across modern BPE
   tokenizers to be a trustworthy cost estimate.
3. Whitespace-word approximation. Last-resort fallback if tiktoken
   itself isn't installed/importable.
"""
import time
import httpx

from app.config import settings, api_for, MODEL_CATALOG

try:
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover - tiktoken should always be installed, but don't hard-fail the demo
    _ENCODING = None


def count_tokens(text: str) -> tuple[int, str]:
    """Exact-as-possible token count for a string of text.

    Returns (token_count, method) where method is one of:
    "tiktoken-cl100k" (exact, free, local) or "whitespace-approx" (fallback).
    """
    if not text:
        return 0, "tiktoken-cl100k" if _ENCODING else "whitespace-approx"
    if _ENCODING is not None:
        return len(_ENCODING.encode(text)), "tiktoken-cl100k"
    return max(1, int(len(text.split()) * 1.3)), "whitespace-approx"


def _mock_reply(prompt: str, flavor: str) -> str:
    return (
        f"[{flavor} model mock reply] Handled a {len(prompt.split())}-word prompt. "
        "Set a real provider in .env to replace this with a live model call."
    )


def call_mistral_model(prompt: str, model_name: str | None = None, api_key: str | None = None) -> tuple[str, int, int, str]:
    """Real call to the Mistral API (OpenAI-compatible chat completions format)."""
    model_name = model_name or "mistral-small-latest"
    key = api_key or settings.mistral_api_key
    try:
        resp = httpx.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={"model": model_name, "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        in_tok, out_tok = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if in_tok is not None and out_tok is not None:
            return text, in_tok, out_tok, "provider-api-exact"
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method
    except Exception as exc:
        text = f"[mistral call failed: {exc}] " + _mock_reply(prompt, "cheap")
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method


def call_openai_model(prompt: str, model_name: str | None = None, api_key: str | None = None) -> tuple[str, int, int, str]:
    """Real call to the OpenAI chat completions API."""
    model_name = model_name or "gpt-4o-mini"
    key = api_key or settings.openai_api_key
    try:
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={"model": model_name, "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        in_tok, out_tok = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if in_tok is not None and out_tok is not None:
            return text, in_tok, out_tok, "provider-api-exact"
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method
    except Exception as exc:
        text = f"[openai call failed: {exc}] " + _mock_reply(prompt, "frontier")
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method


def call_anthropic_model(prompt: str, model_name: str | None = None, api_key: str | None = None) -> tuple[str, int, int, str]:
    """Real call to the Anthropic Messages API."""
    model_name = model_name or "claude-sonnet-5"
    key = api_key or settings.anthropic_api_key
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=model_name,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        return (
            text,
            resp.usage.input_tokens,
            resp.usage.output_tokens,
            "provider-api-exact",
        )
    except Exception as exc:
        text = f"[anthropic call failed: {exc}] " + _mock_reply(prompt, "frontier")
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method


def call_gemini_model(prompt: str, model_name: str | None = None, api_key: str | None = None) -> tuple[str, int, int, str]:
    """Real call to the Google Gemini API (generateContent)."""
    model_name = model_name or "gemini-1.5-flash"
    key = api_key or settings.gemini_api_key
    try:
        resp = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
            params={"key": key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata") or {}
        in_tok, out_tok = usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
        if in_tok is not None and out_tok is not None:
            return text, in_tok, out_tok, "provider-api-exact"
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method
    except Exception as exc:
        text = f"[gemini call failed: {exc}] " + _mock_reply(prompt, "cheap")
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method


def call_huggingface_model(prompt: str, model_name: str | None = None, api_key: str | None = None) -> tuple[str, int, int, str]:
    """Real call to Hugging Face's Inference Providers router. An
    OpenAI-compatible chat completions endpoint that fronts many backend
    providers (Together, Fireworks, Cerebras, Novita, ...) behind a single
    free-to-obtain HF token. Docs: https://huggingface.co/docs/inference-providers

    model_name should be the HF model id, e.g. "meta-llama/Llama-3.1-8B-Instruct"
    or "deepseek-ai/DeepSeek-V3-0324". You can optionally suffix a routing
    policy (":fastest" | ":cheapest" | ":preferred"). If none is given,
    HF defaults to ":fastest".
    """
    model_name = model_name or "meta-llama/Llama-3.1-8B-Instruct"
    key = api_key or settings.hf_api_key
    if not key:
        text = f"[no Hugging Face API token configured. Add one to run '{model_name}' live] " + _mock_reply(
            prompt, "frontier" if MODEL_CATALOG.get(model_name, {}).get("tier") == "frontier" else "cheap"
        )
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method
    try:
        resp = httpx.post(
            "https://router.huggingface.co/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={"model": model_name, "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        in_tok, out_tok = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if in_tok is not None and out_tok is not None:
            return text, in_tok, out_tok, "provider-api-exact"
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method
    except httpx.HTTPStatusError as exc:
        # Surface the actual HF error body (bad token, rate limit, model
        # needs a warm-up, etc.) instead of a generic message, since this
        # is almost always a token/permission/model-id issue the person
        # can fix themselves.
        try:
            detail = exc.response.json().get("error", exc.response.text)
        except Exception:
            detail = exc.response.text
        text = f"[hugging face call failed: HTTP {exc.response.status_code}. {detail}] " + _mock_reply(prompt, "cheap")
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method
    except Exception as exc:
        text = f"[hugging face call failed: {exc}] " + _mock_reply(prompt, "cheap")
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method


def call_ollama_model(prompt: str, model_name: str | None = None) -> tuple[str, int, int, str]:
    """Real call to a local Ollama server."""
    model_name = model_name or settings.cheap_model_name
    try:
        resp = httpx.post(
            f"{settings.ollama_base_url}/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response", "")
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method
    except Exception as exc:  # fall back to mock so the demo never hard-fails
        text = f"[ollama unreachable: {exc}] " + _mock_reply(prompt, "cheap")
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method


def call_model(
    prompt: str,
    model_name: str,
    anthropic_key: str | None = None,
    openai_key: str | None = None,
    hf_key: str | None = None,
) -> tuple[str, int, int, str]:
    """Single dispatch point used by the router: looks up which real API a
    model belongs to (MODEL_CATALOG[model_name]['api']) and calls it if a
    key is available. Either passed in for this one request (from the
    dashboard's key fields) or configured in .env. No key, no matching
    provider, or an unrecognized model name all fall back to a clearly
    labeled mock reply instead of failing the request."""
    api = api_for(model_name)

    if api == "anthropic":
        key = anthropic_key or settings.anthropic_api_key
        if key:
            return call_anthropic_model(prompt, model_name, api_key=key)
        flavor = "frontier" if MODEL_CATALOG.get(model_name, {}).get("tier") == "frontier" else "cheap"
        text = f"[no Anthropic API key configured. Add one to run '{model_name}' live] " + _mock_reply(prompt, flavor)
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method

    if api == "openai":
        key = openai_key or settings.openai_api_key
        if key:
            return call_openai_model(prompt, model_name, api_key=key)
        flavor = "frontier" if MODEL_CATALOG.get(model_name, {}).get("tier") == "frontier" else "cheap"
        text = f"[no OpenAI API key configured. Add one to run '{model_name}' live] " + _mock_reply(prompt, flavor)
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method

    if api == "mistral":
        if settings.mistral_api_key:
            return call_mistral_model(prompt, model_name)
        flavor = "frontier" if MODEL_CATALOG.get(model_name, {}).get("tier") == "frontier" else "cheap"
        text = f"[no Mistral API key configured. Add one to run '{model_name}' live] " + _mock_reply(prompt, flavor)
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method

    if api == "huggingface":
        key = hf_key or settings.hf_api_key
        if key:
            return call_huggingface_model(prompt, model_name, api_key=key)
        flavor = "frontier" if MODEL_CATALOG.get(model_name, {}).get("tier") == "frontier" else "cheap"
        text = f"[no Hugging Face API token configured. Add one to run '{model_name}' live] " + _mock_reply(prompt, flavor)
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method

    if api == "ollama":
        return call_ollama_model(prompt, model_name)

    if api == "gemini":
        if settings.gemini_api_key:
            return call_gemini_model(prompt, model_name)
        flavor = "frontier" if MODEL_CATALOG.get(model_name, {}).get("tier") == "frontier" else "cheap"
        text = f"[no Gemini API key configured. Add one to run '{model_name}' live] " + _mock_reply(prompt, flavor)
        in_tok, method = count_tokens(prompt)
        out_tok, _ = count_tokens(text)
        return text, in_tok, out_tok, method

    # api == "mock", or an unrecognized model name
    flavor = "frontier" if MODEL_CATALOG.get(model_name, {}).get("tier") == "frontier" else "cheap"
    text = _mock_reply(prompt, flavor)
    in_tok, method = count_tokens(prompt)
    out_tok, _ = count_tokens(text)
    return text, in_tok, out_tok, method


def call_cheap_model(prompt: str, model_name: str | None = None) -> tuple[str, int, int, str]:
    """Kept for backward compatibility / direct use outside the router.
    The router itself now calls call_model() so the actual network
    dispatch always matches the selected model, not just the tier."""
    return call_model(prompt, model_name or settings.cheap_model_name)


def call_frontier_model(prompt: str, model_name: str | None = None) -> tuple[str, int, int, str]:
    """Kept for backward compatibility / direct use outside the router."""
    return call_model(prompt, model_name or settings.frontier_model_name)


_METHOD_LABELS = {
    "provider-api-exact": "returned directly by the provider's API as billed usage. Exact.",
    "tiktoken-cl100k": "counted locally with tiktoken's cl100k_base tokenizer (free, offline, no API call). Exact token count for that encoding.",
    "whitespace-approx": "estimated as ~1.3 tokens per whitespace-separated word. Tiktoken wasn't available, so this is a rough fallback only.",
}


def explain_tokens(prompt: str, input_tokens: int, output_tokens: int, method: str) -> str:
    """Plain-English explanation of how the token count was produced."""
    word_count = len(prompt.split())
    label = _METHOD_LABELS.get(method, method)
    return (
        f"Input: {input_tokens} tokens ({word_count}-word prompt), "
        f"Output: {output_tokens} tokens. Counting method: {label}"
    )


def explain_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    input_price: float,
    output_price: float,
    input_cost: float,
    output_cost: float,
    total_cost: float,
    route: str,
) -> str:
    """Plain-English breakdown of why a request cost what it cost."""
    driver = "output tokens" if output_cost >= input_cost else "input tokens"
    tier_note = (
        "routed to the frontier tier, which charges more per token in exchange for stronger reasoning"
        if route == "frontier"
        else "routed to the cheap tier, which trades some capability for a much lower per-token rate"
    )
    return (
        f"{model_name} charges ${input_price:.5f}/1K input tokens and ${output_price:.5f}/1K output tokens. "
        f"{input_tokens} input tokens -> ${input_cost:.6f}, {output_tokens} output tokens -> ${output_cost:.6f}. "
        f"Total ${total_cost:.6f}. This request was {tier_note}, and {driver} made up the larger share of the cost."
    )


def timed_call(fn, prompt: str, model_name: str | None = None):
    start = time.perf_counter()
    text, in_tok, out_tok, method = fn(prompt, model_name)
    latency_ms = int((time.perf_counter() - start) * 1000)
    return text, in_tok, out_tok, method, latency_ms
