"""Automatic quality scores for LLM debriefs, measured against the static analysis.

The static findings are the ground truth: a good debrief keeps their order, carries their fixes,
adds nothing that isn't in the input and stays short and pasteable.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .manager import unverified_numbers

# Words that show a finding was mentioned (cause) and that its fix was carried over (fix).
# Matching is case-insensitive on word stems.
KEYWORDS: dict[str, tuple[list[str], list[str]]] = {
    "stab_gap_deaths": (["stab", "stability"], ["stagger", "hold", "save", "before contact",
                                                "re-stab", "restab", "firebrand"]),
    "stab_gap_deaths_nostab": (["stab", "stability"], ["re-apply", "reapply", "time", "reserve",
                                                       "after", "firebrand"]),
    "boon_wipe": (["strip", "corrupt", "boons dropped", "lost boons", "boon"],
                  ["reapply", "re-apply", "aegis", "block", "resistance", "move"]),
    "strip_balance": (["strip"], ["strip", "spellbreaker", "scourge", "before", "bomb"]),
    "strip_balance_good": (["strip"], []),
    "out_of_position": (["tag", "position", "far", "stack", "straggl", "caught"],
                        ["tag", "stay", "range", "stick", "chas"]),
    "early_cascade": (["opening", "open", "engage", "first", "early", "start"],
                      ["boon", "pre-stack", "prestack", "stack", "bait", "full"]),
    "cleanse_pressure": (["condi", "condition"], ["cleans", "resist"]),
    "downstate_own": (["picked up", "rez", "res ", "ress", "rall", "downed allies", "died"],
                      ["rez", "res ", "ress", "rall", "banner", "downed"]),
    "downstate_enemy": (["escap", "got back", "got up", "convert", "enemy downs", "finish"],
                        ["cleave", "stomp", "push", "finish", "cc"]),
    "downstate_enemy_good": (["down", "kill", "convert"], []),
    "sustain_decline": (["sustain", "heal", "second half"], ["pace", "cooldown", "reset", "heal"]),
    "sustain_low": (["sustain", "heal"], ["heal", "support", "short"]),
    "comp_audit": (["party", "parties", "support"], ["party", "parties", "rebalanc", "move",
                                                     "support"]),
    "comp_audit_loners": (["party", "parties"], ["invite", "party", "parties"]),
    "outnumbered": (["outnumber", "enemies", "vs", "bigger", "more enemies"],
                    ["choke", "siege", "wall", "split", "bait"]),
    "player_outliers": (["underperform", "below", "player"], ["build", "gear", "pair", "explain"]),
}

PROFESSIONS = {
    "Guardian", "Dragonhunter", "Firebrand", "Willbender", "Luminary", "Warrior", "Berserker",
    "Spellbreaker", "Bladesworn", "Paragon", "Revenant", "Herald", "Renegade", "Vindicator",
    "Conduit", "Engineer", "Scrapper", "Holosmith", "Mechanist", "Amalgam", "Ranger", "Druid",
    "Soulbeast", "Untamed", "Galeshot", "Thief", "Daredevil", "Deadeye", "Specter", "Antiquary",
    "Elementalist", "Tempest", "Weaver", "Catalyst", "Evoker", "Mesmer", "Chronomancer",
    "Mirage", "Virtuoso", "Troubadour", "Necromancer", "Reaper", "Scourge", "Harbinger",
    "Ritualist",
}


@dataclass
class Score:
    words: int = 0
    format_ok: bool = False
    result_ok: bool = False
    invented_numbers: list[str] = field(default_factory=list)
    invented_names: list[str] = field(default_factory=list)
    top1_mentioned: bool = False
    top1_first: bool = False
    top_recall: float = 0.0  # share of the top-3 issues mentioned under "Why"
    fix_coverage: float = 0.0  # share of the top-2 issues whose fix appears under "Change"
    reference: float | None = None  # share of reference points covered (if a reference exists)
    padded: bool = False  # more "Why" bullets than problems in the input (invented reasons)
    positives_ok: bool = True  # "Went well" reflects the input (mentions it / says nothing)
    total: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _has(text: str, words: list[str]) -> bool:
    t = text.lower()
    return any(w.lower() in t for w in words)


def sections(text: str) -> dict[str, str]:
    """Split a debrief into result / why / change / well parts (tolerant of formatting)."""
    t = text.replace("**", "")
    parts = {"result": "", "why": "", "change": "", "well": ""}
    current = "result"
    for line in t.splitlines():
        low = line.strip().lower().lstrip("#").strip()
        if low.startswith("why"):
            current = "why"
        elif low.startswith("change") or low.startswith("next time"):
            current = "change"
        elif low.startswith("went well") or low.startswith("what went well"):
            current = "well"
        parts[current] += line + "\n"
    return parts


def bullets(section: str) -> list[str]:
    return [ln.strip()[1:].strip() for ln in section.splitlines()
            if ln.strip().startswith(("-", "*", "•")) or re.match(r"^\s*\d+[.)]", ln)]


def score(text: str, user_text: str, summary: dict[str, Any], notes: dict[str, Any],
          player_names: list[str], reference: list[dict[str, Any]] | None = None) -> Score:
    sc = Score()
    sc.words = len(text.split())
    secs = sections(text)
    n_why, n_change = len(bullets(secs["why"])), len(bullets(secs["change"]))
    sc.format_ok = (1 <= n_why <= 3 and 1 <= n_change <= 3 and sc.words <= 180
                    and "<think>" not in text and not re.search(r"[\U0001F300-\U0001FAFF]", text))
    result = summary.get("result") or ""
    sc.result_ok = result in secs["result"].lower() or (result == "skirmish"
                                                         and "skirmish" in text.lower())
    sc.invented_numbers = unverified_numbers(text, user_text)
    user_low = user_text.lower()
    sc.invented_names = sorted(
        {n for n in player_names if len(n) > 3 and n in text and n.lower() not in user_low}
        | {p for p in PROFESSIONS if re.search(rf"\b{p}\b", text, re.I)
           and p.lower() not in user_low})

    issues = notes.get("issues", [])
    why = secs["why"] or text
    change = secs["change"]
    why_bullets = bullets(secs["why"])
    if issues:
        k1 = KEYWORDS.get(issues[0]["key"], ([], []))[0]
        sc.top1_mentioned = _has(why, k1)
        sc.top1_first = bool(why_bullets) and _has(why_bullets[0], k1)
        top = issues[:3]
        sc.top_recall = sum(_has(why, KEYWORDS.get(f["key"], ([], []))[0]) for f in top) / len(top)
        with_fix = [f for f in issues[:2] if KEYWORDS.get(f["key"], ([], []))[1]]
        if with_fix:
            sc.fix_coverage = sum(_has(change, KEYWORDS[f["key"]][1]) for f in with_fix) / len(
                with_fix)
        else:
            sc.fix_coverage = 1.0
    else:
        sc.top1_mentioned = sc.top1_first = True
        sc.top_recall = sc.fix_coverage = 1.0

    sc.padded = len(why_bullets) > max(1, min(len(issues), 3))
    pos = notes.get("positives", [])
    well = secs["well"].lower()
    if pos:
        k = KEYWORDS.get(pos[0]["key"], ([], []))[0] or pos[0]["title"].lower().split()
        sc.positives_ok = _has(well, k)
    else:
        sc.positives_ok = not well or any(w in well for w in ("nothing", "none", "no "))

    if reference:
        hit = sum(1 for p in reference if any(_has(text, grp) for grp in p["any"]))
        sc.reference = hit / len(reference)

    # Weighted total out of 100. Inventing facts is the worst failure, so it costs the most.
    total = (
        20 * sc.top1_first + 10 * sc.top1_mentioned + 20 * sc.top_recall + 20 * sc.fix_coverage
        + 10 * sc.format_ok + 5 * sc.result_ok + 5 * sc.positives_ok
        + (15 * sc.reference if sc.reference is not None else 15 * sc.top_recall)
    )
    total -= 15 * min(len(sc.invented_numbers), 3) + 15 * min(len(sc.invented_names), 3)
    total -= 15 * sc.padded
    total = total * 100 / 105  # keep the scale at 100
    sc.total = round(max(total, 0.0), 1)
    return sc


_STOP = {"with", "that", "this", "from", "were", "their", "they", "them", "than", "only",
         "when", "into", "have", "been", "your", "about", "after", "before", "every", "while",
         "under", "over", "just", "like", "more", "most", "some", "much", "also", "even"}
_WORD = re.compile(r"[a-zA-Z][a-zA-Z'-]{3,}")


def _stems(text: str) -> set[str]:
    return {w.lower()[:6] for w in _WORD.findall(text) if w.lower() not in _STOP}


def reference_similarity(text: str, reference: str) -> float:
    """How much of a reference debrief an output covers (0-1): content words + numbers."""
    body = text.split("\n", 1)[1] if text.startswith("Result:") else text
    ref_words, out_words = _stems(reference), _stems(body)
    ref_nums = set(re.findall(r"\d+(?:[.:]\d+)?", reference))
    out_nums = set(re.findall(r"\d+(?:[.:]\d+)?", body))
    w = len(ref_words & out_words) / len(ref_words) if ref_words else 1.0
    n = len(ref_nums & out_nums) / len(ref_nums) if ref_nums else 1.0
    return round(0.5 * w + 0.5 * n, 3)
