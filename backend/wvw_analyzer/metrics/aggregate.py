"""Session (raid night) aggregation across analyzed fights."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .columns import ALL_COLUMNS

NUMERIC = [c for c in ALL_COLUMNS if c.fmt != "text" and c.key != "group"]

LEADERBOARDS = [
    ("damage", "Damage"),
    ("down_contribution", "Down contribution"),
    ("against_downed", "Damage to downed"),
    ("strips", "Strips"),
    ("cleanses", "Cleanses"),
    ("healing", "Healing"),
    ("barrier", "Barrier"),
    ("gen_squadBuffs_1122", "Stability given"),
    ("resurrects", "Resurrects"),
    ("deaths", "Deaths"),
]


def _strip_title(title: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


def aggregate_session(items: list[dict[str, Any]]) -> dict[str, Any]:
    results: dict[str, int] = defaultdict(int)
    gvg_rounds: dict[str, int] = defaultdict(int)  # round results across GvG fights
    totals = {"squadDeaths": 0, "enemyDeaths": 0, "squadDowns": 0, "enemyDowns": 0,
              "durationS": 0.0, "squadDamage": 0.0}
    players: dict[str, dict[str, Any]] = {}
    issues: dict[str, dict[str, Any]] = {}
    positives: dict[str, dict[str, Any]] = {}
    fights = []

    for it in items:
        s = it["summary"]
        results[s.get("result", "even")] += 1
        for r in s.get("rounds") or [] if s.get("mode") == "gvg" else []:
            gvg_rounds[r["result"]] += 1
        for k in totals:
            totals[k] += s.get(k) or 0
        fights.append({"id": it["id"], "map": s.get("map"), "start": s.get("start"),
                       "result": s.get("result"), "durationS": s.get("durationS"),
                       "squadDeaths": s.get("squadDeaths"), "enemyDeaths": s.get("enemyDeaths"),
                       "squadCount": s.get("squadCount"), "enemyCount": s.get("enemyCount"),
                       "topIssue": s.get("topIssue"), "mode": s.get("mode", "zerg"),
                       "rounds": len(s.get("rounds") or []),
                       "roundWins": s.get("roundWins"), "roundLosses": s.get("roundLosses")})
        for bucket, target in (("issues", issues), ("more", issues), ("positives", positives)):
            for f in (it["notes"] or {}).get(bucket, []):
                # GvG wording variants count as the same recurring problem.
                key = (f.get("key") or f["detector"]).removesuffix("_gvg")
                e = target.setdefault(key, {"key": key, "title": _strip_title(f["title"]),
                                            "count": 0, "fights": [], "losses": 0,
                                            "severity": f["severity"], "occurrences": []})
                if it["id"] not in e["fights"]:
                    e["count"] += 1
                    e["fights"].append(it["id"])
                    e["losses"] += s.get("result") == "loss"
                    # What earned the entry in this fight: the code-written one-line fact.
                    e["occurrences"].append({
                        "fightId": it["id"], "start": s.get("start"), "map": s.get("map"),
                        "result": s.get("result"), "mode": s.get("mode", "zerg"),
                        "findingKey": f.get("key") or f["detector"],
                        "severity": f["severity"], "impact": f.get("impact", 0.0),
                        "short": f.get("short") or f.get("cause") or "",
                    })
        for r in it["players"] or []:
            if not r.get("in_fight", True):
                continue
            acc = r.get("account") or r["name"]
            p = players.setdefault(acc, {"account": acc, "names": set(), "professions": set(),
                                         "fights": 0, "sums": defaultdict(float)})
            p["names"].add(r["name"])
            p["professions"].add(r["profession"])
            p["fights"] += 1
            for c in NUMERIC:
                p["sums"][c.key] += float(r.get(c.key) or 0)

    rows = []
    for acc, p in players.items():
        row: dict[str, Any] = {"account": acc, "name": ", ".join(sorted(p["names"])),
                               "profession": ", ".join(sorted(p["professions"])),
                               "fights": p["fights"]}
        for c in NUMERIC:
            total = p["sums"][c.key]
            row[c.key] = total if c.agg == "sum" else total / p["fights"]
        rows.append(row)

    boards = {}
    for key, label in LEADERBOARDS:
        ranked = sorted((r for r in rows if r.get(key)), key=lambda r: -r[key])[:10]
        boards[key] = {
            "label": label,
            "rows": [{"account": r["account"], "name": r["name"], "profession": r["profession"],
                      "fights": r["fights"], "total": r[key],
                      "perFight": r[key] / max(r["fights"], 1)} for r in ranked],
        }

    for e in (*issues.values(), *positives.values()):
        e["occurrences"].sort(key=lambda o: (-(o["impact"] or 0), o["start"] or ""))

    n = max(len(items), 1)
    return {
        "fights": fights,
        "totals": {**totals, "fights": len(items), "results": dict(results),
                   "gvgRounds": dict(gvg_rounds),
                   "kdr": round(totals["enemyDeaths"] / max(totals["squadDeaths"], 1), 2)},
        "players": sorted(rows, key=lambda r: -r["fights"]),
        "columns": [c.meta() for c in ALL_COLUMNS],
        "leaderboards": boards,
        # Problems that show up in lost fights matter most; ubiquitous minor notes sink.
        "recurringIssues": sorted(
            ({**v, "share": round(100 * v["count"] / n)} for v in issues.values()),
            key=lambda v: (-(v["losses"] * 2 + v["count"] * (0.3 if v["severity"] == "minor"
                                                              else 1.0)), -v["count"])),
        "positives": sorted(positives.values(), key=lambda v: -v["count"]),
    }
