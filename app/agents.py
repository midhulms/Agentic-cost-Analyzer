# Agent personas. Author: Cryzal & Midhul
#
# The router already decides a *tier* (cheap/frontier) and a *model*.
# This module adds a human-facing layer on top of that: which named
# "agent" handled the request. The agent is picked from the same
# complexity signals the router already computes (see app/complexity.py),
# so it costs nothing extra to derive and always matches what actually
# happened. No separate classifier, no extra tokens spent.
#
# Priority order matters: a prompt can trip more than one signal
# (e.g. contains code AND asks "why"), so we pick the most specific
# match first and fall back to the tier's default agent last.

AGENT_CATALOG = {
    "compiler": {
        "name": "Compiler",
        "role": "Code Agent",
        "icon": "code",
        "accent": "amber",
        "tagline": "Reads and writes code.",
        "description": "Picked up because the prompt contained code, a function signature, or a query-like structure.",
    },
    "atlas": {
        "name": "Atlas",
        "role": "Planner Agent",
        "icon": "route",
        "accent": "cyan",
        "tagline": "Breaks work into steps.",
        "description": "Picked up because the prompt asked for a plan, workflow, or multi-step sequence.",
    },
    "prism": {
        "name": "Prism",
        "role": "Analyst Agent",
        "icon": "layers",
        "accent": "violet",
        "tagline": "Compares, weighs, explains why.",
        "description": "Picked up because the prompt asked for reasoning: a comparison, evaluation, or root-cause explanation.",
    },
    "voyager": {
        "name": "Voyager",
        "role": "Deep-Dive Agent",
        "icon": "compass",
        "accent": "rose",
        "tagline": "Handles long, dense requests.",
        "description": "Picked up because the prompt was long or asked several distinct questions at once, needing more context held at once.",
    },
    "sparrow": {
        "name": "Sparrow",
        "role": "Quick-Reply Agent",
        "icon": "zap",
        "accent": "teal",
        "tagline": "Fast answers, short prompts.",
        "description": "Picked up because the prompt was short and single-intent. No reasoning, planning, or code signals fired.",
    },
    # Example of a custom, hand-added agent
    # Not derived from complexity.py at all. Just a plain keyword check in
    # pick_agent() below. Copy this pattern for your own agents: add an
    # entry here, then add one `if` branch in pick_agent().
    "echo": {
        "name": "Echo",
        "role": "Summary Agent",
        "icon": "echo",
        "accent": "lime",
        "tagline": "Summarizes and translates.",
        "description": "Picked up because the prompt asked for a summary, TL;DR, or translation.",
    },
}

# Keywords for the custom Echo agent. Simple substring match on the raw
# prompt. This is the easiest way to bolt on a new agent without touching
# complexity.py at all.
_ECHO_MARKERS = ["summarize", "summarise", "tl;dr", "tldr", "in short", "condense", "translate"]

# order = priority. First match wins.
_SELECTION_ORDER = [
    ("contains_code", "compiler"),
    ("multi_step_language", "atlas"),
    ("reasoning_language", "prism"),
]


def pick_agent(signals: dict, route: str, prompt: str = "") -> str:
    """Return an AGENT_CATALOG key given the complexity signals + chosen route."""
    lower = prompt.lower()
    if any(m in lower for m in _ECHO_MARKERS):
        return "echo"

    for signal_key, agent_key in _SELECTION_ORDER:
        if signals.get(signal_key):
            return agent_key

    # No specific signal fired. Split the remaining traffic by tier/length
    # so "everything else" doesn't all collapse into one bucket.
    if route == "frontier" or signals.get("length_words", 0) > 150 or signals.get("question_count", 0) > 1:
        return "voyager"
    return "sparrow"


def agent_info(agent_key: str) -> dict:
    # Falls back to Sparrow for an unknown key (e.g. a bad force_agent value
    # from a client). And the returned "id" reflects the *actual* agent
    # used, not the invalid key that was asked for, so id/name never drift
    # apart in the API response, the DB log, or the dashboard.
    if agent_key in AGENT_CATALOG:
        return {"id": agent_key, **AGENT_CATALOG[agent_key]}
    return {"id": "sparrow", **AGENT_CATALOG["sparrow"]}


def all_agents() -> list[dict]:
    return [{"id": key, **info} for key, info in AGENT_CATALOG.items()]
