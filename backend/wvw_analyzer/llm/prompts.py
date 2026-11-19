"""Prompt variants for the LLM debrief (compared with scripts/llm_bench.py).

Every variant gets the same inputs - the fight summary and the static analyzer's ranked notes -
and must only rephrase them; the analysis itself never comes from the LLM.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

SUMMARY_KEYS = ["map", "durationS", "result", "squadCount", "squadInFight", "allyCount",
                "enemyCount", "squadDowns", "squadDeaths", "enemyDowns", "enemyDeaths",
                "squadStrips", "squadBoonsLost", "squadCleanses"]

MAX_ISSUES = 5


@dataclass(frozen=True)
class PromptVariant:
    name: str
    system: str
    build: Callable[[dict[str, Any], dict[str, Any]], str]
    description: str = ""
    # Optional deterministic text placed before the model's answer (e.g. the result line).
    prefix: Callable[..., str] | None = None  # (summary, notes) -> text


def _mmss(seconds: float | None) -> str:
    s = int(round(seconds or 0))
    return f"{s // 60}:{s % 60:02d}"


# ---- v1: original (JSON input, loose instructions) ---------------------------------------------
V1_SYSTEM = (
    "You are an experienced Guild Wars 2 WvW commander writing a short post-fight debrief for "
    "your squad. Use ONLY the facts and numbers given in the input; never invent numbers, "
    "players or events. Write in plain English: one sentence on the outcome, then 'Why' with "
    "the 2-3 most important causes, then 'Change next time' with 2-3 concrete actions, then "
    "one line on what went well if anything did. Keep it under 180 words. /no_think"
)


def build_json(summary: dict[str, Any], notes: dict[str, Any]) -> str:
    payload = {
        "fight": {k: summary.get(k) for k in SUMMARY_KEYS},
        "problems": [{"title": f["title"], "what_happened": f["cause"],
                      "suggested_fix": f["fix"]} for f in notes.get("issues", [])[:MAX_ISSUES]],
        "went_well": [{"title": f["title"], "detail": f["cause"]}
                      for f in notes.get("positives", [])],
    }
    return json.dumps(payload, ensure_ascii=False, indent=1)


# ---- v2: plain-text input, fixed output template, explicit rules ---------------------------
OUTPUT_TEMPLATE = """Result: <win/loss/even> - <one short sentence with kills, deaths and numbers>
Why:
- <problem 1 in one sentence, with its time if given>
- <problem 2>
- <problem 3, only if important>
Change next time:
- <concrete action for problem 1>
- <concrete action for problem 2>
Went well: <one line, or "nothing notable">"""

V2_SYSTEM = (
    "You write post-fight debriefs for a Guild Wars 2 WvW squad. You receive the results of an "
    "automatic fight analysis. Rewrite them as a short, direct debrief a commander can paste "
    "in squad chat.\n\nRules:\n"
    "- Use only facts from the input. Copy numbers, times and names exactly; never add new "
    "ones.\n"
    "- Problems are already ranked: problem 1 is the main reason. Keep that order and mention "
    "problem 1 first.\n"
    "- Every 'Change next time' line must be a concrete action taken from the problem's "
    "suggested fix, not generic advice.\n"
    "- Plain words, no headings other than the template, no emojis, under 160 words.\n\n"
    f"Answer exactly in this format:\n{OUTPUT_TEMPLATE}\n/no_think"
)


def build_text(summary: dict[str, Any], notes: dict[str, Any]) -> str:
    s = summary
    lines = [
        f"Fight: {s.get('map')}, {_mmss(s.get('durationS'))} long, result: {s.get('result')}.",
        f"Numbers: squad {s.get('squadInFight') or s.get('squadCount')} (+{s.get('allyCount') or 0}"
        f" allies) vs {s.get('enemyCount')} enemies.",
        f"Our downs/deaths: {s.get('squadDowns')}/{s.get('squadDeaths')}. Enemy downs/deaths: "
        f"{s.get('enemyDowns')}/{s.get('enemyDeaths')}.",
        "",
        "Problems (ranked, most important first):",
    ]
    issues = notes.get("issues", [])[:MAX_ISSUES]
    if not issues:
        lines.append("(none detected)")
    for i, f in enumerate(issues, 1):
        lines.append(f"{i}. {f['title']}")
        lines.append(f"   What happened: {f['cause']}")
        lines.append(f"   Suggested fix: {f['fix']}")
    lines += ["", "Went well:"]
    pos = notes.get("positives", [])
    lines += [f"- {f['title']}: {f['cause']}" for f in pos] or ["(nothing detected)"]
    return "\n".join(lines)


# ---- v3: v2 + one worked example (synthetic fight, no real player data) --------------------
EXAMPLE_INPUT = """Fight: Eternal Battlegrounds, 2:10 long, result: loss.
Numbers: squad 30 (+2 allies) vs 38 enemies.
Our downs/deaths: 24/19. Enemy downs/deaths: 9/4.

Problems (ranked, most important first):
1. Stability gap during enemy bomb (0:42)
   What happened: At 0:42, 8 players went down in one burst (7 died). Stability coverage just before was low in party 2 (12%), 4 (30%), and 6 of the 8 downed players had no stability.
   Suggested fix: Keep stability ready for the enemy push, not the approach. Stagger the firebrands (one opens, one holds for the enemy bomb), call stab right before contact, and re-stab after the first exchange.
2. Losing the strip war
   What happened: Enemies removed 640 boons from the squad, while the squad stripped 310. Only 3 player(s) contributed meaningful strips.
   Suggested fix: Bring or activate more strip-capable builds and time the strip skills to land right before your damage bomb.
3. Enemy downs escaped
   What happened: Only 4 of 9 enemy downs (44%) were turned into kills; 5 got back up.
   Suggested fix: After a bomb, push through downed enemies with cleave and stomps, and use CC to stop res attempts.

Went well:
(nothing detected)"""

EXAMPLE_OUTPUT = """Result: loss - 19 deaths for 4 kills, 30 vs 38.
Why:
- At 0:42 the enemy bomb downed 8 of us in one burst; parties 2 and 4 had almost no stability.
- We lost the strip war: 640 boons stripped from us vs 310 by us, with only 3 real strippers.
- 5 of 9 enemy downs got back up.
Change next time:
- Firebrands stagger stab: one opens, one holds it for the enemy push; call stab right before contact.
- Strippers fire right before our bomb so the enemy loses stability when our damage hits.
- After our bomb, push the downs with cleave, stomps and CC on res attempts.
Went well: nothing notable."""


def few_shot(summary: dict[str, Any], notes: dict[str, Any]) -> str:
    return build_text(summary, notes)


# ---- v4: code writes the result line; the model only condenses the top 3 problems ----------
def result_line(summary: dict[str, Any]) -> str:
    """Deterministic first line, so the outcome and headline numbers can't be misquoted."""
    s = summary
    def n(count: Any, word: str) -> str:
        return f"{count} {word}{'' if count == 1 else 's'}"

    allies = f" (+{n(s['allyCount'], 'ally').replace('allys', 'allies')})" if s.get(
        "allyCount") else ""
    numbers = f"{s.get('squadInFight') or s.get('squadCount')}{allies} vs {s.get('enemyCount')}"
    if s.get("mode") == "gvg":
        return gvg_result_line(s, numbers, n)
    return (f"Result: {s.get('result')} - {n(s.get('enemyDeaths'), 'kill')} for "
            f"{n(s.get('squadDeaths'), 'death')}, {numbers} enemies, "
            f"{_mmss(s.get('durationS'))}.")


def gvg_result_line(s: dict[str, Any], numbers: str, n: Any) -> str:
    """GvG: round results, counted kills only, and what was left at the call-off."""
    rounds = s.get("rounds") or []
    kills = s.get("enemyDeaths", 0) - s.get("enemyDeathsLate", 0)
    deaths = s.get("squadDeaths", 0) - s.get("squadDeathsLate", 0)
    if len(rounds) > 1:
        outcome = (f"GvG {s.get('result')} {s.get('roundWins', 0)}-{s.get('roundLosses', 0)} "
                   f"over {len(rounds)} rounds")
    else:
        outcome = f"GvG round {s.get('result')}"
    line = (f"Result: {outcome} - {n(kills, 'kill')} for {n(deaths, 'death')}, {numbers}, "
            f"{_mmss(s.get('fightS') or s.get('durationS'))}.")
    left_sq, left_en = s.get("squadDownsLeft", 0), s.get("enemyDownsLeft", 0)
    if left_sq or left_en:
        line += (f"\nLeft at the call-off (not counted): {left_en} enemy "
                 f"down{'' if left_en == 1 else 's'}, {left_sq} of ours.")
    return line


V4_TEMPLATE = """Why:
- <problem 1 in one short sentence, with its key number or time>
- <one bullet per further problem>
Change next time:
- <the fix for problem 1 as one concrete instruction>
- <one bullet per further problem>
Went well: <summary of the first 'Went well' item, or "nothing notable" if there is none>"""

V4_SYSTEM = (
    "You condense an automatic Guild Wars 2 WvW fight analysis into squad-chat bullet points. "
    "The problems are already ranked by importance.\n\nRules:\n"
    "- Write exactly as many 'Why' and 'Change next time' bullets as there are problems in the "
    "input (the input says how many), in the given order. Never invent, merge or reorder "
    "problems.\n"
    "- Only use facts from the input. Copy numbers and times exactly. Do not name players or "
    "professions unless the input does.\n"
    "- Each 'Change next time' bullet is the problem's suggested fix, shortened to one direct "
    "instruction.\n"
    "- No intro, no outro, no extra headings. Under 120 words.\n\n"
    f"Answer exactly in this format:\n{V4_TEMPLATE}\n/no_think"
)


V5_TEMPLATE = """Why:
- <problem 1 title>: <its most important fact, copied from What happened>
- <one bullet per further problem, same form>
Change next time:
- <the fix for problem 1 as one direct instruction>
- <one bullet per further problem>
Went well: <the first 'Went well' item in a few words, or "nothing notable">"""

V5_SYSTEM = (
    "You condense an automatic Guild Wars 2 WvW fight analysis into squad-chat bullet points. "
    "The problems are already ranked by importance.\n\nRules:\n"
    "- Write exactly as many 'Why' and 'Change next time' bullets as there are problems in the "
    "input (the input says how many), in the given order. Never invent, merge or reorder "
    "problems.\n"
    "- Start every 'Why' bullet with the problem's title, then a colon and its single most "
    "important fact from 'What happened', with the numbers copied exactly.\n"
    "- Each 'Change next time' bullet is the problem's suggested fix as one direct "
    "instruction.\n"
    "- Max 25 words per bullet. Do not name players or professions unless the input does. "
    "Do not add facts or opinions.\n"
    "- Always finish with the 'Went well' line. No intro, outro or other headings.\n\n"
    f"Answer exactly in this format:\n{V5_TEMPLATE}\n/no_think"
)


def build_compact(summary: dict[str, Any], notes: dict[str, Any]) -> str:
    issues = notes.get("issues", [])[:3]
    n = len(issues)
    lines = [f"Problems: {n} (ranked, most important first). Write exactly {n} 'Why' bullet"
             f"{'' if n == 1 else 's'} and {n} 'Change next time' bullet{'' if n == 1 else 's'}."]
    if not issues:
        lines = ["Problems: none detected. Write one 'Why' bullet saying no clear mistakes were "
                 "found and one 'Change next time' bullet: keep the same approach."]
    for i, f in enumerate(issues, 1):
        lines += [f"{i}. {f['title']}", f"   What happened: {f['cause']}",
                  f"   Suggested fix: {f['fix']}"]
    lines += ["", "Went well:"]
    lines += [f"- {f['title']}: {f['cause']}" for f in notes.get("positives", [])] or [
        "(nothing detected)"]
    return "\n".join(lines)


# ---- v6: v5 + severity labels and a code-decided framing, shorter bullets --------------------
def framing(summary: dict[str, Any], notes: dict[str, Any]) -> str:
    """How the debrief should sound - decided by code, not by the model."""
    issues = notes.get("issues", [])[:3]
    result = summary.get("result")
    serious = [f for f in issues if f["severity"] in ("critical", "major")]
    if result == "skirmish" and not serious:
        return ("Small skirmish without real losses. Start the first Why bullet with "
                "'Small skirmish, nothing important.' and keep everything brief.")
    if result == "win" and not serious:
        return ("Clean win. Start the first Why bullet with 'Clean win, only small things to "
                "tidy up.' and present the problems as minor.")
    if result == "win":
        return "A win, but the problems below still cost players. Name them plainly."
    return "These problems decided the fight. Name them plainly, most important first."


V6_TEMPLATE = """Why:
- <problem 1 title>: <its key fact with the numbers, max 25 words>
- <one bullet per further problem, same form>
Change next time:
- <fix for problem 1 as one short instruction, max 15 words>
- <one bullet per further problem>
Went well: <the first 'Went well' item in a few words, or "nothing notable">"""

V6_SYSTEM = (
    "You condense an automatic Guild Wars 2 WvW fight analysis into a short squad-chat debrief. "
    "The problems are already ranked by importance and labelled critical, major or minor.\n\n"
    "Rules:\n"
    "- Follow the 'Framing' line of the input.\n"
    "- Write exactly as many 'Why' and 'Change next time' bullets as there are problems, in "
    "the given order. Never invent, merge or reorder problems.\n"
    "- Start every 'Why' bullet with the problem's title, then a colon and its single most "
    "important fact, copying numbers and times exactly. Minor problems get a shorter bullet.\n"
    "- Every 'Change next time' bullet is that problem's suggested fix as one short direct "
    "instruction.\n"
    "- Do not name players or professions unless needed for the fact. Add no facts, numbers "
    "or opinions that are not in the input.\n"
    "- Always finish with the 'Went well' line. No intro, outro or other headings. Under 110 "
    "words in total.\n\n"
    f"Answer exactly in this format:\n{V6_TEMPLATE}\n/no_think"
)


def build_framed(summary: dict[str, Any], notes: dict[str, Any]) -> str:
    issues = notes.get("issues", [])[:3]
    n = len(issues)
    lines = [f"Framing: {framing(summary, notes)}", ""]
    if issues:
        lines.append(f"Problems: {n} (ranked). Write exactly {n} 'Why' bullet"
                     f"{'' if n == 1 else 's'} and {n} 'Change next time' bullet"
                     f"{'' if n == 1 else 's'}.")
    else:
        lines.append("Problems: none detected. Write one 'Why' bullet saying no clear mistakes "
                     "were found and one 'Change next time' bullet: keep the same approach.")
    for i, f in enumerate(issues, 1):
        lines += [f"{i}. [{f['severity']}] {f['title']}", f"   What happened: {f['cause']}",
                  f"   Suggested fix: {f['fix']}"]
    lines += ["", "Went well:"]
    lines += [f"- {f['title']}: {f['cause']}" for f in notes.get("positives", [])] or [
        "(nothing detected)"]
    return "\n".join(lines)


# ---- v7: v6 framing + code-written one-line facts and fixes (nothing to paraphrase) ---------
V7_TEMPLATE = """Why:
- <problem 1 title>: <its fact>
- <one bullet per further problem, same form>
Change next time:
- <fix for problem 1>
- <one bullet per further problem>
Went well: <the 'Went well' item, or "nothing notable">"""

V7_SYSTEM = (
    "You turn an automatic Guild Wars 2 WvW fight analysis into a short squad-chat debrief. "
    "Each problem comes with a title, a one-line fact and a one-line fix, already ranked by "
    "importance and labelled critical, major or minor.\n\n"
    "Rules:\n"
    "- Follow the 'Framing' line of the input.\n"
    "- Write exactly as many 'Why' and 'Change next time' bullets as there are problems, in "
    "the given order.\n"
    "- 'Why' bullet = the problem title, a colon, then its fact. You may make the fact read "
    "more naturally, but keep every number, time and party exactly as given. 'Downed' and "
    "'died' are different things: never change one into the other.\n"
    "- 'Change next time' bullet = the problem's fix as a direct instruction.\n"
    "- Add nothing that is not in the input: no extra facts, numbers, causes, players or "
    "professions.\n"
    "- Always finish with the 'Went well' line. No intro, outro or other headings. Under 110 "
    "words.\n\n"
    f"Answer exactly in this format:\n{V7_TEMPLATE}\n/no_think"
)


def build_short(summary: dict[str, Any], notes: dict[str, Any]) -> str:
    issues = notes.get("issues", [])[:3]
    n = len(issues)
    lines = [f"Framing: {framing(summary, notes)}", ""]
    if issues:
        lines.append(f"Problems: {n} (ranked). Write exactly {n} 'Why' bullet"
                     f"{'' if n == 1 else 's'} and {n} 'Change next time' bullet"
                     f"{'' if n == 1 else 's'}.")
    else:
        lines.append("Problems: none detected. Write one 'Why' bullet saying no clear mistakes "
                     "were found and one 'Change next time' bullet: keep the same approach.")
    for i, f in enumerate(issues, 1):
        lines += [f"{i}. [{f['severity']}] {f['title']}",
                  f"   Fact: {f.get('short') or f['cause']}",
                  f"   Fix: {f.get('fix_short') or f['fix']}"]
    pos = notes.get("positives", [])
    lines += ["", "Went well: " + ("; ".join(
        f"{f['title']} ({(f.get('short') or f['cause']).rstrip('.')})" for f in pos)
        if pos else "nothing detected")]
    return "\n".join(lines)


# ---- v8: v7, but the framing sentence is code-written into the header ------------------------
def framing_line(summary: dict[str, Any], notes: dict[str, Any]) -> str | None:
    issues = notes.get("issues", [])[:3]
    serious = [f for f in issues if f["severity"] in ("critical", "major")]
    if summary.get("mode") == "gvg":  # every GvG round is a deliberate fight, never "a skirmish"
        if summary.get("result") == "win" and not serious:
            return "Clean GvG win, only small things to tidy up:"
        return None
    if summary.get("result") == "skirmish" and not serious:
        return "Small skirmish, nothing important - just a few small things:"
    if summary.get("result") == "win" and not serious:
        return "Clean win, only small things to tidy up:"
    return None


def header_v8(summary: dict[str, Any], notes: dict[str, Any] | None = None) -> str:
    line = result_line(summary)
    extra = framing_line(summary, notes or {})
    return f"{line}\n{extra}" if extra else line


V8_SYSTEM = (
    "You turn an automatic Guild Wars 2 WvW fight analysis into a short squad-chat debrief. "
    "Each problem comes with a title, a one-line fact and a one-line fix, already ranked by "
    "importance.\n\n"
    "Rules:\n"
    "- Write exactly as many 'Why' and 'Change next time' bullets as there are problems, in "
    "the given order, one bullet per problem.\n"
    "- 'Why' bullet = the problem title, a colon, then its fact. You may make the fact read "
    "more naturally, but keep every number, time, party and 'It happened N times' sentence. "
    "'Downed' and 'died' are different things: never change one into the other.\n"
    "- 'Change next time' bullet = the problem's fix as a direct instruction.\n"
    "- Add nothing that is not in the input: no extra facts, numbers, causes, players or "
    "professions.\n"
    "- Always finish with the 'Went well' line. No intro, outro or other headings. Under 100 "
    "words.\n\n"
    f"Answer exactly in this format:\n{V7_TEMPLATE}\n/no_think"
)


def build_v8(summary: dict[str, Any], notes: dict[str, Any]) -> str:
    text = build_short(summary, notes)
    # The framing is already in the code-written header; the model only gets the facts.
    return "\n".join(line for line in text.splitlines() if not line.startswith("Framing:"))


VARIANTS: dict[str, PromptVariant] = {
    "v1_json": PromptVariant("v1_json", V1_SYSTEM, build_json, "original JSON prompt"),
    "v2_text": PromptVariant("v2_text", V2_SYSTEM, build_text,
                             "plain-text input, strict template and rules"),
    "v3_example": PromptVariant("v3_example", V2_SYSTEM, few_shot,
                                "v2 plus one worked example"),
    "v4_compact": PromptVariant("v4_compact", V4_SYSTEM, build_compact,
                                "code writes the result line; model condenses top 3 problems",
                                prefix=result_line),
    "v5_anchored": PromptVariant("v5_anchored", V5_SYSTEM, build_compact,
                                 "v4 + bullets start with the problem title and its key fact",
                                 prefix=result_line),
    "v6_framed": PromptVariant("v6_framed", V6_SYSTEM, build_framed,
                               "v5 + severity labels, code-decided framing, shorter bullets",
                               prefix=result_line),
    "v7_short": PromptVariant("v7_short", V7_SYSTEM, build_short,
                              "v6 framing + code-written one-line facts and fixes",
                              prefix=result_line),
    "v8_header": PromptVariant("v8_header", V8_SYSTEM, build_v8,
                               "v7 with the framing sentence written by code in the header",
                               prefix=header_v8),
}


DEFAULT = "v8_header"


def messages(variant: str, summary: dict[str, Any], notes: dict[str, Any]
             ) -> tuple[list[dict[str, str]], str]:
    """Chat messages for a variant and the user text (used to verify numbers afterwards)."""
    v = VARIANTS[variant]
    user = v.build(summary, notes)
    msgs = [{"role": "system", "content": v.system}]
    if variant.startswith("v3"):
        msgs += [{"role": "user", "content": EXAMPLE_INPUT},
                 {"role": "assistant", "content": EXAMPLE_OUTPUT}]
    msgs.append({"role": "user", "content": user})
    if v.prefix:  # numbers in the prefix come from the analysis, so they count as input too
        user = _prefix(v, summary, notes) + "\n" + user
    return msgs, user


def _prefix(v: PromptVariant, summary: dict[str, Any], notes: dict[str, Any] | None) -> str:
    try:
        return v.prefix(summary, notes)  # type: ignore[misc]
    except TypeError:
        return v.prefix(summary)  # type: ignore[misc]


def finalize(variant: str, summary: dict[str, Any], text: str,
             notes: dict[str, Any] | None = None) -> str:
    """Full debrief text: deterministic prefix (if any) + the model's answer."""
    v = VARIANTS[variant]
    return f"{_prefix(v, summary, notes)}\n{text.strip()}" if v.prefix else text.strip()
