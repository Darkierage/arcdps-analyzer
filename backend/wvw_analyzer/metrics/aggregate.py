"""Session (raid night) aggregation across analyzed fights."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .columns import ALL_COLUMNS
from .table import squad_row

NUMERIC = [c for c in ALL_COLUMNS if c.fmt != "text" and c.key != "group"]
# Per-player fight distances (not table columns on their own): time-weighted like the others.
EXTRA_TIME = ("fight_dist_tag", "fight_dist_stack")
# Per-fight values for the session trend chart (squad, each party, each player).
TREND_KEYS = ["up_1122", "gen_squadBuffs_1122", "strips", "cleanses", "incoming_strips",
              "damage", "downs", "deaths", "fight_dist_tag"]
# A rate leaderboard (uptime, generation) only ranks players with this share of the session's
# fight time, so one short fight can't top it.
RATE_BOARD_MIN_SHARE = 0.25

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
RULES = {c.key: c.session_agg for c in NUMERIC} | {k: "time" for k in EXTRA_TIME}
# EI's per-fight distances: -1 when there is nothing to measure from (no commander in the
# fight, no stack), and the commander's own distance to tag is 0. Neither is a distance, so
# they are left out of the session averages instead of pulling them toward 0.
EI_DISTANCES = ("dist_to_com", "stack_dist")
# Values that can be missing for a whole session row (shown as "–", not 0).
NULLABLE = set(EXTRA_TIME) | set(EI_DISTANCES)
# Column metadata for the session tables. EI's "Active time" becomes the time the session
# numbers are based on (see `_Combine.row`).
SESSION_COLUMNS = [
    {**c.meta(), "label": "Time in fights",
     "description": "Time in this session's fights: EI's active time in each fight, or the "
                    "fight's length when EI has none. DPS, per minute and Min. time use it."}
    if c.key == "active_s" else c.meta()
    for c in ALL_COLUMNS
]


class _Combine:
    """Combines one player's (or one party's / the squad's) rows over a session's fights,
    following each column's session rule (see `columns.SessionAgg`).

    Group rows (party, squad) weight by fight duration, and their DPS (the members' DPS added
    up) is a rate like uptime. Player rows weight by the player's time in the fight.
    """

    def __init__(self, group: bool = False):
        self.group = group
        self.fights = 0
        self.time = 0.0  # summed weights: seconds in fights
        self.sums: dict[str, float] = defaultdict(float)
        self.wsums: dict[str, float] = defaultdict(float)
        self.weights: dict[str, float] = defaultdict(float)

    def add(self, row: dict[str, Any], weight: float) -> None:
        self.fights += 1
        self.time += weight
        for k, rule in RULES.items():
            v = row.get(k)
            if v is None:
                continue
            if rule == "time" or (rule == "dps" and self.group):
                self.wsums[k] += float(v) * weight
                self.weights[k] += weight
            else:
                self.sums[k] += float(v)

    def row(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        per_min: dict[str, float] = {}
        minutes = self.time / 60.0
        for k, rule in RULES.items():
            if rule == "time" or (rule == "dps" and self.group):
                w = self.weights[k]
                out[k] = self.wsums[k] / w if w else (None if k in NULLABLE else 0.0)
            elif rule == "dps":
                out[k] = self.sums["damage"] / self.time if self.time else 0.0
            else:
                out[k] = self.sums[k]
                per_min[k] = self.sums[k] / minutes if minutes else 0.0
        # "Time in fights": the seconds DPS, per minute, Min. time and the rate-board rule use
        # (EI's active time, else the fight's length), so the column agrees with them.
        out["active_s"] = self.time
        per_min.pop("active_s", None)
        out["fights"] = self.fights
        out["activeS"] = self.time
        out["perMin"] = per_min
        return out


def _weight(row: dict[str, Any], duration: float) -> float:
    """Seconds a player was in the fight (EI active time), else the fight's length."""
    return float(row.get("active_s") or 0) or duration


def _without_missing(row: dict[str, Any]) -> dict[str, Any]:
    """A stored row with EI's "no distance" values (see `EI_DISTANCES`) as None."""
    out = dict(row)
    for k in EI_DISTANCES:
        v = out.get(k)
        if v is not None and (v < 0 or (k == "dist_to_com" and out.get("is_commander"))):
            out[k] = None
    return out


def _merge_split(rows: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    """One row per account. EI splits a player into several rows in one fight (e.g. after a
    spec change); for the session they are one player in one fight: counts add up, rates are
    weighted by each row's active time, and the main (longest) row gives party and name.
    Each merged row keeps its source rows in `_rows`."""
    by_acc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_acc[r.get("account") or r["name"]].append(r)
    out = []
    for parts in by_acc.values():
        if len(parts) == 1:
            out.append({**parts[0], "_rows": parts})
            continue
        # Each row by its own active time; only when EI has none for any of them, the fight's
        # length shared between them. The merged row's `active_s` is the same total, so the
        # time shown, DPS and per minute agree with the weights of the rates.
        active = [float(r.get("active_s") or 0) for r in parts]
        total = sum(active)
        weights = active if total else [duration / len(parts)] * len(parts)
        main = parts[max(range(len(parts)), key=lambda i: weights[i])]
        merged: dict[str, Any] = {**main, "_rows": parts}
        for k, rule in RULES.items():
            vals = [(float(r[k]), w) for r, w in zip(parts, weights, strict=True)
                    if r.get(k) is not None]
            if not vals:
                merged[k] = None
            elif rule == "sum":
                merged[k] = sum(v for v, _ in vals)
            else:
                tw = sum(w for _, w in vals)
                merged[k] = sum(v * w for v, w in vals) / tw if tw else vals[0][0]
        merged["active_s"] = total  # 0 when EI has none: `_weight` then uses the fight length
        merged["is_commander"] = any(r.get("is_commander") for r in parts)
        merged["has_heal_data"] = any(r.get("has_heal_data") for r in parts)
        out.append(merged)
    return out


def _group_row(members: list[dict[str, Any]]) -> dict[str, Any]:
    """One fight's party / squad row from its in-fight members (as on the fight page), plus
    the members' mean fight distances."""
    row = squad_row(members)
    for k in (*EXTRA_TIME, *EI_DISTANCES):
        vals = [m[k] for m in members if m.get(k) is not None]
        row[k] = sum(vals) / len(vals) if vals else None
    return row


def _trend_values(row: dict[str, Any] | None) -> dict[str, float | None]:
    if row is None:
        return dict.fromkeys(TREND_KEYS)
    return {k: None if row.get(k) is None else round(float(row[k]), 1) for k in TREND_KEYS}


def _member_mean(members: list[dict[str, Any]]) -> dict[str, float | None]:
    """The average in-fight player of one fight (the reference line on a player's trend)."""
    out: dict[str, float | None] = {}
    for k in TREND_KEYS:
        vals = [float(m[k]) for m in members if m.get(k) is not None]
        out[k] = sum(vals) / len(vals) if vals else None
    return out


def _ranked(c: Counter) -> list[Any]:
    return [v for v, _ in c.most_common()]


def _strip_title(title: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


def _counted(s: dict[str, Any], key: str) -> int | None:
    """Kills or deaths that count: in GvG, those after a call-off are left out."""
    v = s.get(key)
    return None if v is None else v - (s.get(key + "Late") or 0)


def aggregate_session(items: list[dict[str, Any]], detail: bool = True) -> dict[str, Any]:
    """The session summary. With `detail=False` (the overlay's poll) only the results, totals,
    recurring problems and strengths are built: no player, party or squad rows, leaderboards
    or trend, and the items need no `players`."""
    results: dict[str, int] = defaultdict(int)
    gvg_rounds: dict[str, int] = defaultdict(int)  # round results across GvG fights
    totals = {"squadDeaths": 0, "enemyDeaths": 0, "squadDowns": 0, "enemyDowns": 0,
              "durationS": 0.0, "squadDamage": 0.0}
    players: dict[str, dict[str, Any]] = {}
    parties: dict[int, dict[str, Any]] = {}
    squad = _Combine(group=True)
    trend_squad: list[dict[str, float | None]] = []
    trend_avg: list[dict[str, float | None]] = []
    trend_parties: dict[int, dict[int, dict[str, float | None]]] = {}
    trend_players: dict[str, dict[int, dict[str, float | None]]] = {}
    issues: dict[str, dict[str, Any]] = {}
    positives: dict[str, dict[str, Any]] = {}
    fights = []

    for fi, it in enumerate(items):
        s = it["summary"]
        results[s.get("result", "even")] += 1
        for r in s.get("rounds") or [] if s.get("mode") == "gvg" else []:
            gvg_rounds[r["result"]] += 1
        for k in totals:
            # GvG: downs and deaths after a call-off don't count (the fight page agrees).
            totals[k] += (s.get(k) or 0) - (s.get(k + "Late") or 0)
        fights.append({"id": it["id"], "map": s.get("map"), "start": s.get("start"),
                       "result": s.get("result"), "durationS": s.get("durationS"),
                       "squadDeaths": _counted(s, "squadDeaths"),
                       "enemyDeaths": _counted(s, "enemyDeaths"),
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
        if not detail:
            continue
        duration = float(s.get("durationS") or 0)
        rows_in = [_without_missing(r) for r in it.get("players") or []
                   if r.get("in_fight", True)]
        merged_in = _merge_split(rows_in, duration)
        if rows_in:
            sq = _group_row(rows_in)
            squad.add(sq, duration)
            trend_squad.append(_trend_values(sq))
            trend_avg.append(_trend_values(_member_mean(merged_in)))
        else:
            trend_squad.append(_trend_values(None))
            trend_avg.append(_trend_values(None))
        by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for r in rows_in:
            by_group[int(r.get("group") or 0)].append(r)
        for g, members in by_group.items():
            pr = _group_row(members)
            pa = parties.setdefault(g, {"combine": _Combine(group=True), "accounts": Counter(),
                                        "professions": Counter(), "sizes": []})
            pa["combine"].add(pr, duration)
            # In row order (not a set): ties in `accounts` must not depend on the hash seed.
            accs = list(dict.fromkeys(m.get("account") or m["name"] for m in members))
            pa["sizes"].append(len(accs))
            for a in accs:
                pa["accounts"][a] += 1
            for m in members:
                pa["professions"][m["profession"]] += 1
            trend_parties.setdefault(g, {})[fi] = _trend_values(pr)
        for r in merged_in:
            acc = r.get("account") or r["name"]
            p = players.setdefault(acc, {"combine": _Combine(), "names": Counter(),
                                         "professions": Counter(), "groups": Counter(),
                                         "commander": False, "heal": False})
            for part in r["_rows"]:
                p["names"][part["name"]] += 1
                p["professions"][part["profession"]] += 1
            p["groups"][r.get("group")] += 1
            p["commander"] |= bool(r.get("is_commander"))
            p["heal"] |= bool(r.get("has_heal_data"))
            p["combine"].add(r, _weight(r, duration))
            trend_players.setdefault(acc, {})[fi] = _trend_values(r)

    for e in (*issues.values(), *positives.values()):
        e["occurrences"].sort(key=lambda o: (-(o["impact"] or 0), o["start"] or ""))

    n = max(len(items), 1)
    out: dict[str, Any] = {
        "fights": fights,
        "totals": {**totals, "fights": len(items), "results": dict(results),
                   "gvgRounds": dict(gvg_rounds),
                   "kdr": round(totals["enemyDeaths"] / max(totals["squadDeaths"], 1), 2)},
        # Problems that show up in lost fights matter most; ubiquitous minor notes sink.
        "recurringIssues": sorted(
            ({**v, "share": round(100 * v["count"] / n)} for v in issues.values()),
            key=lambda v: (-(v["losses"] * 2 + v["count"] * (0.3 if v["severity"] == "minor"
                                                              else 1.0)), -v["count"])),
        "positives": sorted(positives.values(), key=lambda v: -v["count"]),
    }
    if not detail:
        return out

    rows = []
    for acc, p in players.items():
        row: dict[str, Any] = {
            "account": acc, "name": ", ".join(_ranked(p["names"])),
            # Most played first: its color marks the player.
            "profession": ", ".join(_ranked(p["professions"])),
            "group": _ranked(p["groups"])[0],
            "is_commander": p["commander"], "has_heal_data": p["heal"],
            **p["combine"].row()}
        rows.append(row)

    party_rows = []
    for g in sorted(parties):
        pa = parties[g]
        accounts = _ranked(pa["accounts"])
        # Usual size: in-fight players per fight it was in; `accounts` is everyone over the
        # session (most fights first).
        party_rows.append({**pa["combine"].row(), "name": f"Party {g}", "group": g,
                           "profession": "", "account": "", "accounts": accounts,
                           "members": round(sum(pa["sizes"]) / len(pa["sizes"])),
                           "professions": sorted(pa["professions"])})
    squad_out = {**squad.row(), "name": "Squad", "group": 0, "profession": "", "account": ""}

    session_s = totals["durationS"]
    boards = {}
    for key, label in LEADERBOARDS:
        rate = RULES[key] == "time"
        pool = [r for r in rows if r.get(key)
                and (not rate or r["activeS"] >= RATE_BOARD_MIN_SHARE * session_s)]
        ranked = sorted(pool, key=lambda r: -r[key])[:10]
        boards[key] = {
            "label": label,
            "rate": rate,
            "rows": [{"account": r["account"], "name": r["name"], "profession": r["profession"],
                      "fights": r["fights"], "total": r[key],
                      "perFight": None if rate else r[key] / max(r["fights"], 1)}
                     for r in ranked],
        }

    nf = len(items)

    def series(per_fight: dict[int, dict[str, float | None]]) -> dict[str, list]:
        return {k: [per_fight[i][k] if i in per_fight else None for i in range(nf)]
                for k in TREND_KEYS}

    trend = {
        "keys": TREND_KEYS,
        "squad": {k: [v[k] for v in trend_squad] for k in TREND_KEYS},
        "playerAvg": {k: [v[k] for v in trend_avg] for k in TREND_KEYS},
        "parties": {str(g): series(v) for g, v in sorted(trend_parties.items())},
        "players": {acc: series(v) for acc, v in trend_players.items()},
    }

    return {
        **out,
        "players": sorted(rows, key=lambda r: -r["fights"]),
        "parties": party_rows,
        "squad": squad_out,
        "trend": trend,
        "columns": SESSION_COLUMNS,
        "leaderboards": boards,
    }


# Results that decide a session's win rate. A skirmish (fewer than 3 deaths in total) is no
# deliberate fight, so it is left out, as on the Sessions cards (W / E / L).
DECIDED = ("win", "loss", "even")


def session_trend(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per session for the Trends page, in the order given.

    Each session is a session row (`id`, `name`, `kind`, `start`) with `items`: its analyzed
    fights' summaries and notes, as `aggregate_session(detail=False)` takes them. Every number
    comes from that session summary, so this page and the session's own page agree. Sessions
    without analyzed fights are left out."""
    out = []
    for s in sessions:
        if not s["items"]:
            continue
        agg = aggregate_session(s["items"], detail=False)
        totals = agg["totals"]
        results = {k: totals["results"].get(k, 0) for k in (*DECIDED, "skirmish")}
        decided = sum(results[k] for k in DECIDED)
        top = agg["recurringIssues"][0] if agg["recurringIssues"] else None
        out.append({
            "id": s["id"], "name": s["name"], "kind": s["kind"], "start": s["start"],
            "fights": totals["fights"],
            "results": results,
            # None when the session had skirmishes only: there is no rate to show.
            "winRate": round(100 * results["win"] / decided, 1) if decided else None,
            "kdr": totals["kdr"],
            "deathsPerFight": round(totals["squadDeaths"] / totals["fights"], 1),
            "squadDeaths": totals["squadDeaths"], "enemyDeaths": totals["enemyDeaths"],
            "topIssue": None if top is None else {
                "key": top["key"], "title": top["title"], "count": top["count"],
                "losses": top["losses"], "severity": top["severity"]},
        })
    return out
