"""
Heuristic complexity scorer.

Author: midhul:Cryzal

This is intentionally transparent and dependency-free so it's easy to explain
and to swap out later (e.g. for a small trained classifier). It returns a
score in [0, 1]; the router compares that to settings.complexity_threshold.

Signals used:
- length of the prompt (longer prompts tend to need more reasoning)
- presence of code / structured data
- multi-step or planning language ("then", "after that", "step by step")
- explicit reasoning requests ("explain why", "compare", "analyze")
- number of distinct questions in one prompt
"""
import re

MULTI_STEP_MARKERS = [
    "step by step", "then ", "after that", "first,", "next,", "finally,",
    "plan", "workflow", "multi-step",
]

REASONING_MARKERS = [
    "why", "analyze", "analyse", "compare", "evaluate", "explain the",
    "trade-off", "tradeoff", "reasoning", "root cause", "optimi",
]

CODE_PATTERN = re.compile(r"```|def |class |SELECT |import |function\(|<\w+>")
QUESTION_PATTERN = re.compile(r"\?")


def score(prompt: str) -> float:
    text = prompt.strip()
    if not text:
        return 0.0

    length_score = min(len(text) / 1200, 1.0)                       # long prompt -> higher
    word_count = len(text.split())
    length_word_score = min(word_count / 200, 1.0)

    lower = text.lower()
    multi_step_score = 1.0 if any(m in lower for m in MULTI_STEP_MARKERS) else 0.0
    reasoning_score = 1.0 if any(m in lower for m in REASONING_MARKERS) else 0.0
    code_score = 1.0 if CODE_PATTERN.search(text) else 0.0

    question_count = len(QUESTION_PATTERN.findall(text))
    multi_question_score = min(question_count / 3, 1.0)

    # Weighted blend -- weights are a starting point, tune against real traffic.
    weighted = (
        0.20 * length_score
        + 0.15 * length_word_score
        + 0.25 * multi_step_score
        + 0.20 * reasoning_score
        + 0.10 * code_score
        + 0.10 * multi_question_score
    )
    return round(min(weighted, 1.0), 3)


def score_with_explanation(prompt: str) -> dict:
    """
    Same scoring logic as score(), but also returns which signals fired
    and a plain-English reason -- used to explain routing + token decisions
    in the API response and dashboard.
    """
    text = prompt.strip()
    if not text:
        return {"score": 0.0, "signals": {}, "reason": "Empty prompt."}

    word_count = len(text.split())
    lower = text.lower()

    signals = {
        "length_chars": len(text),
        "length_words": word_count,
        "multi_step_language": any(m in lower for m in MULTI_STEP_MARKERS),
        "reasoning_language": any(m in lower for m in REASONING_MARKERS),
        "contains_code": bool(CODE_PATTERN.search(text)),
        "question_count": len(QUESTION_PATTERN.findall(text)),
    }

    fired = []
    if signals["length_words"] > 150:
        fired.append(f"long prompt ({signals['length_words']} words)")
    if signals["multi_step_language"]:
        fired.append("multi-step / planning language")
    if signals["reasoning_language"]:
        fired.append("reasoning or comparison language")
    if signals["contains_code"]:
        fired.append("contains code")
    if signals["question_count"] > 1:
        fired.append(f"{signals['question_count']} distinct questions")

    reason = (
        "Flagged as complex due to: " + ", ".join(fired) + "."
        if fired else
        "Short, single-intent prompt with no complexity signals detected."
    )

    return {"score": score(prompt), "signals": signals, "reason": reason}
