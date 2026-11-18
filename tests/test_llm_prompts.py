from factory import zerg
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.config import Settings
from wvw_analyzer.llm import prompts
from wvw_analyzer.llm.scoring import score


def _analysis():
    a = analyze_ei(zerg(10, downs_at=[30, 30.5, 31, 31.5], strips=5, boons_lost=30), "x",
                   Settings())
    return a.summary, a.notes, [p["name"] for p in a.stats["players"]]


def test_every_variant_builds_messages():
    summary, notes, _ = _analysis()
    for name in prompts.VARIANTS:
        msgs, user = prompts.messages(name, summary, notes)
        assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"
        assert notes["issues"][0]["title"] in user


def test_v4_prefix_is_deterministic_and_counts_as_input():
    summary, notes, _ = _analysis()
    _, user = prompts.messages("v4_compact", summary, notes)
    line = prompts.result_line(summary)
    assert user.startswith(line)
    full = prompts.finalize("v4_compact", summary, "Why:\n- x\nChange next time:\n- y")
    assert full.startswith("Result: ")


def test_scoring_rewards_faithful_and_penalizes_invention():
    summary, notes, players = _analysis()
    _, user = prompts.messages("v2_text", summary, notes)
    top = notes["issues"][0]
    good = (f"Result: {summary['result']} - {summary['squadDeaths']} deaths.\n"
            f"Why:\n- {top['title']}\nChange next time:\n- {top['fix']}\n"
            "Went well: nothing notable")
    bad = good + "\nAlso 987 enemies and the Willbender carried."
    s_good = score(good, user, summary, notes, players)
    s_bad = score(bad, user, summary, notes, players)
    assert s_good.top1_first and s_good.format_ok and not s_good.invented_numbers
    assert s_bad.invented_numbers == ["987"] and "Willbender" in s_bad.invented_names
    assert s_bad.total < s_good.total


def test_v8_is_default_and_frames_clean_wins_in_code():
    from wvw_analyzer.config import LlmSettings

    assert LlmSettings().prompt == prompts.DEFAULT == "v8_header"
    summary, notes, _ = _analysis()
    minor = {"issues": [{**notes["issues"][0], "severity": "minor"}], "positives": []}
    assert prompts.framing_line({**summary, "result": "win"}, minor).startswith("Clean win")
    assert prompts.framing_line({**summary, "result": "loss"}, minor) is None
    _, user = prompts.messages("v8_header", {**summary, "result": "win"}, minor)
    assert "Clean win" in user.splitlines()[1]  # code-written header, not left to the model
    assert "Framing:" not in user


def test_short_facts_are_rendered():
    _, notes, _ = _analysis()
    for f in notes["issues"]:
        assert f["short"] and "{" not in f["short"]
