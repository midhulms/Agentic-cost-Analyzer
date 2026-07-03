from app.complexity import score


def test_simple_prompt_scores_low():
    assert score("What's the capital of France?") < 0.4


def test_empty_prompt_scores_zero():
    assert score("") == 0.0
    assert score("   ") == 0.0


def test_multistep_prompt_scores_higher():
    simple = score("What's 2 + 2?")
    complex_ = score(
        "First analyze our Q3 churn drivers, then compare them against Q2, "
        "explain the trade-offs of each retention strategy step by step, "
        "and finally recommend which one to prioritize and why."
    )
    assert complex_ > simple


def test_code_bumps_score():
    plain = score("Say hello")
    with_code = score("Say hello ```def hello(): return 'hi'```")
    assert with_code > plain
