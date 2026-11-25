"""Per-fight facts about each squad member, for the personal review ("My play").

Extracted in the analysis worker (they need the Elite Insights JSON) and stored per row in
`player_fights`. They are ingredients, not verdicts: the rules in `coach/` read them at request
time, so the same facts serve a fight, a session or a profile, and thresholds can change without
a re-analysis.

Every number a rule compares has its baseline stored next to it: the rest of the squad's downs
in this fight (to judge a player's downs against the squad's, never as a bare share) and, per
metric, the median of the other players with the same spec *and the same job* (same spec is
not same job) and the squad median.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Any

import numpy as np

from .summary import Metrics
from .timeline import PlayerTimeline

FACTS_VERSION = 1
NEAR_DOWN_S = 4.0  # other squad downs within this many seconds: the down was part of a bomb
HP_BEFORE_S = 3  # health this many seconds before a down
MIN_ACTIVE_SHARE = 0.5  # rows active for less of the fight are no one's peer (as player_outliers)
TOP_SKILLS = 5
RECAP_SKILLS = 3

# The jobs a row can have: its strongest output relative to the squad median (as in
# `player_outliers`, but per row and per minute of the row's own active time).
JOBS = {
    "damage": "damage",
    "strips": "strips",
    "cleanses": "cleanses",
    "healing": "healing",
    "stab": "gen_squadBuffs_1122",
}
# An output only counts as a row's job when it reaches this share of the squad's strong
# players in that fight (90th percentile of those with any); no job when none does. A
# relative bar: absolute per-minute minimums (player_outliers') left a third of rows without
# a job in quiet fights, so a player's job flipped between fights (calibration, step 2).
JOB_SHARE_OF_TOP = 0.25
JOB_TOP_QUANTILE = 0.9

# Metrics stored with peer references: (stat row column or fact, per minute?). The first five
# are the jobs' own metrics.
PEER_METRICS: dict[str, tuple[str, bool]] = {
    "damage": ("damage", True),
    "down_contribution": ("down_contribution", True),
    "strips": ("strips", True),
    "cleanses": ("cleanses", True),
    "healing": ("healing", True),
    "stab": ("gen_squadBuffs_1122", False),
    "damage_taken": ("damage_taken", True),
    "deaths": ("deaths", True),
    "dodges": ("@dodges", True),
    "cc_taken": ("incoming_cc", True),
    "cast": ("@cast", False),
    "cancel_s": ("@cancel_s", True),
    "dist_tag": ("fight_dist_tag", False),
    "stab_up": ("up_1122", False),
}


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _r(v: float | None, nd: int = 3) -> float | None:
    """Round to `nd` significant digits (enough for comparisons, compact in JSON)."""
    if v is None or not math.isfinite(v):
        return None
    if v == 0:
        return 0
    digits = max(nd - 1 - int(math.floor(math.log10(abs(v)))), 0)
    out = round(v, digits)
    return int(out) if digits == 0 else out


class _Names:
    """Skill and buff names from the log's maps; conditions are buffs (indirect damage)."""

    def __init__(self, raw: dict[str, Any]):
        self.skills = raw.get("skillMap") or {}
        self.buffs = raw.get("buffMap") or {}

    def __call__(self, sid: int, indirect: bool = False) -> str:
        order = ((self.buffs, "b"), (self.skills, "s"))
        for table, prefix in order if indirect else order[::-1]:
            entry = table.get(f"{prefix}{sid}")
            if entry and entry.get("name"):
                return str(entry["name"])
        return f"#{sid}"

    def classification(self, bid: int) -> str | None:
        return (self.buffs.get(f"b{bid}") or {}).get("classification")

    def dodge_ids(self) -> set[int]:
        out = set()
        for k, v in self.skills.items():
            if (v or {}).get("name") == "Dodge" and k[1:].lstrip("-").isdigit():
                out.add(int(k[1:]))
        return out


def _clamped_s(intervals: list[list[float]], end_ms: float) -> float:
    """Seconds inside the log. EI marks "until the log ends" with a huge end time."""
    return sum(max(0.0, min(float(e), end_ms) - max(float(s), 0.0))
               for s, e in intervals) / 1000.0


def _spec_of(src: str | None) -> str | None:
    if not src or src == "UNKNOWN":
        return None
    return src.split(" pl-")[0] if " pl-" in src else src


def _recap(entry: dict[str, Any], names: _Names) -> dict[str, Any] | None:
    """The hits that took the player down: span, enemies, and the top skills by damage."""
    hits = [h for h in entry.get("toDown") or [] if (h.get("damage") or 0) > 0]
    if not hits:
        return None
    times = [float(h.get("time") or 0) for h in hits]
    total = float(sum(h["damage"] for h in hits))
    by_skill: dict[tuple[bool, int], float] = defaultdict(float)
    specs: dict[tuple[bool, int], Counter] = defaultdict(Counter)
    for h in hits:
        k = (bool(h.get("indirectDamage")), int(h.get("id") or 0))
        by_skill[k] += h["damage"]
        if spec := _spec_of(h.get("src")):
            specs[k][spec] += 1
    srcs = {h.get("src") for h in hits if _spec_of(h.get("src"))}
    top = sorted(by_skill.items(), key=lambda kv: (-kv[1], kv[0][1]))[:RECAP_SKILLS]
    return {
        "span": _r((max(times) - min(times)) / 1000.0, 2),
        "enemies": len(srcs) or None,  # None: the log doesn't name the sources
        "top": [{"skill": names(sid, ind), "share": _r(dmg / total, 2),
                 "spec": specs[(ind, sid)].most_common(1)[0][0] if specs[(ind, sid)] else None}
                for (ind, sid), dmg in top],
    }


def _skill_table(dist: list[dict[str, Any]], names: _Names, taken: bool) -> list[dict] | None:
    rows = [d for d in dist or [] if (d.get("totalDamage") or 0) > 0]
    if not rows:
        return None
    total = float(sum(d["totalDamage"] for d in rows))
    rows.sort(key=lambda d: (-d["totalDamage"], d.get("id") or 0))
    out = []
    for d in rows[:TOP_SKILLS]:
        hits = int(d.get("hits") or 0)
        item: dict[str, Any] = {
            "skill": names(int(d.get("id") or 0), bool(d.get("indirectDamage"))),
            "damage": int(d["totalDamage"]),
            "share": _r(d["totalDamage"] / total, 2),
            "hits": hits,
        }
        if not taken and hits:
            item["connected"] = _r((d.get("connectedHits") or 0) / hits, 2)
            item["blocked"] = int(d.get("blocked") or 0)
            item["evaded"] = int(d.get("evaded") or 0)
            item["missed"] = int(d.get("missed") or 0)
        out.append(item)
    return out


def _per_min(v: float | None, active_s: float) -> float | None:
    if v is None:
        return None
    return float(v) / max(active_s / 60.0, 1 / 60)


def _row_scalars(row: dict[str, Any], pt: PlayerTimeline, names: _Names, dodge_ids: set[int],
                 end_ms: float) -> dict[str, Any]:
    p = pt.player
    stats = p.first("statsAll")
    cast = stats.get("skillCastUptimeNoAA")
    cast = float(cast) if isinstance(cast, (int, float)) and 0 <= cast <= 100 else None
    rotation = p.raw.get("rotation")
    dodges = None
    if rotation:
        dodges = sum(len(r.get("skills") or []) for r in rotation if r.get("id") in dodge_ids)
    cons = p.raw.get("consumables")
    classes = {names.classification(int(c.get("id") or 0)) for c in cons or []}
    return {
        "dead_s": _r(_clamped_s(p.dead_intervals, end_ms)),
        "downed_s": _r(_clamped_s(p.down_intervals, end_ms)),
        "cast": _r(cast),
        "cancels": int(stats.get("wasted") or 0),
        "cancel_s": _r(float(stats.get("timeWasted") or 0)),
        "dodges": dodges,
        "food": None if cons is None else "Nourishment" in classes,
        "utility": None if cons is None else "Enhancement" in classes,
    }


def _metric(row: dict[str, Any], scalars: dict[str, Any], name: str) -> float | None:
    src, per_min = PEER_METRICS[name]
    if name == "healing" and not row.get("has_heal_data"):
        return None
    v = scalars.get(src[1:]) if src.startswith("@") else row.get(src)
    if v is None:
        return None
    v = float(v)
    return _per_min(v, float(row.get("active_s") or 0)) if per_min else v


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    return vals[min(len(vals) - 1, int(q * (len(vals) - 1) + 0.5))]


def _job(values: dict[str, float | None], squad: dict[str, tuple[float | None, float | None]]
         ) -> str | None:
    """The output this row is strongest in relative to the squad median, among those that
    reach a share of the squad's strong players; None when none does. `values` are per minute
    (squad stability given is already a rate); `squad` holds (median, top) per job."""
    best, best_rel = None, 0.0
    for job in JOBS:
        v = values.get(job)
        med, top = squad.get(job, (None, None))
        if not v or not top or v < JOB_SHARE_OF_TOP * top:
            continue
        rel = v / med if med else 10.0
        if rel > best_rel:
            best, best_rel = job, rel
    return best


def personal_facts(m: Metrics) -> list[dict[str, Any]]:
    """One entry per squad row: identity columns for `player_fights` and the `facts` dict."""
    fight, tl = m.fight, m.timeline
    end_ms = float(fight.duration_ms)
    dur_s = max(fight.duration_s, 1e-9)
    names = _Names(fight.raw)
    dodge_ids = names.dodge_ids()
    pts = tl.players
    rows = m.players
    account = {pt.key: (pt.player.account or pt.player.name) for pt in pts}
    scalars = [_row_scalars(r, pt, names, dodge_ids, end_ms) for r, pt in zip(rows, pts,
                                                                          strict=True)]

    # Peers and squad medians: in-fight rows active for at least half the fight, without the
    # commander (as in player_outliers).
    def eligible(i: int) -> bool:
        r = rows[i]
        return bool(pts[i].in_fight and not r.get("is_commander")
                    and float(r.get("active_s") or 0) >= MIN_ACTIVE_SHARE * dur_s)

    pool = [i for i in range(len(rows)) if eligible(i)]
    values = [{k: _metric(r, scalars[i], k) for k in PEER_METRICS} for i, r in enumerate(rows)]
    job_ref: dict[str, tuple[float | None, float | None]] = {}
    for job in JOBS:  # the job metrics share their names with PEER_METRICS
        vals = [values[i][job] for i in pool if values[i][job] is not None]
        # The strong players among those who produce this output at all, so that a lone
        # specialist (the squad's one healer) still has a job.
        job_ref[job] = (_median(vals), _quantile([v for v in vals if v > 0], JOB_TOP_QUANTILE))
    jobs = [_job(values[i], job_ref) for i in range(len(rows))]

    # Squad downs that count: not left at a GvG call-off and not after one.
    judged = [(d, k) for d, k in zip(tl.squad_downs, tl.squad_down_keys, strict=True)
              if d["round"] is not None and not d["left"]]
    by_key = {pt.key: pt for pt in pts}
    down_facts = [_down_fact(d, k, by_key, pts, tl, judged) for d, k in judged]
    order: list[str] = []  # accounts in the order they first went down
    for (_, k) in judged:
        if account[k] not in order:
            order.append(account[k])

    in_fight_idx = [i for i in range(len(rows)) if pts[i].in_fight]
    out = []
    for i, (row, pt) in enumerate(zip(rows, pts, strict=True)):
        acc = account[pt.key]
        # rank: the down's place among the squad's judged downs in this fight (1 = first).
        mine = [{**f, "rank": n} for n, (f, (_, k)) in
                enumerate(zip(down_facts, judged, strict=True), 1) if k == pt.key]
        left = [_down_fact(d, k, by_key, pts, tl, judged, judge=False)
                for d, k in zip(tl.squad_downs, tl.squad_down_keys, strict=True)
                if k == pt.key and (d["round"] is None or d["left"])]
        others_idx = [j for j in in_fight_idx if account[pts[j].key] != acc]
        others_down = [f for f, (_, k) in zip(down_facts, judged, strict=True)
                       if account[k] != acc]
        same_spec = [j for j in pool if account[pts[j].key] != acc
                     and rows[j]["profession"] == row["profession"]]
        peer_idx = [j for j in same_spec if jobs[j] == jobs[i]]
        squad_idx = [j for j in pool if account[pts[j].key] != acc]
        peers = {}
        for k in PEER_METRICS:
            pv = [values[j][k] for j in peer_idx if values[j][k] is not None]
            sv = [values[j][k] for j in squad_idx if values[j][k] is not None]
            peers[k] = [_r(values[i][k]), _r(_median(pv)), len(pv), _r(_median(sv))]
        # The same-spec players by their job in this fight: [count, median of the job's own
        # metric, of cast time, of cancelled-cast seconds per minute]. A player is judged on
        # the job they had in most fights on a spec, also in fights where this row's job
        # came out differently.
        spec_peers = {}
        for job in JOBS:
            idx = [j for j in same_spec if jobs[j] == job]
            if idx:
                spec_peers[job] = [len(idx)] + [
                    _r(_median([values[j][k] for j in idx if values[j][k] is not None]))
                    for k in (job, "cast", "cancel_s")]
        party = [j for j in others_idx if rows[j]["group"] == row["group"]]
        party_stab = [float(rows[j].get("up_1122") or 0) for j in party]
        facts = {
            "v": FACTS_VERSION,
            "mode": tl.mode,
            "dur_s": _r(dur_s, 4),
            "active_s": _r(float(row.get("active_s") or 0), 4),
            "spec": row["profession"],
            "job": jobs[i],
            "eligible": i in pool,  # active long enough to be compared with peers
            **scalars[i],
            "downs": mine,
            "downs_left": left,
            "first_rank": 1 + order.index(acc) if acc in order else None,
            "squad": {
                "players": len({account[pts[j].key] for j in in_fight_idx}),
                "downs_total": len(judged),
                "players_downed": len(order),
                # The rest of the squad (other accounts, in the fight): their time, time
                # dead and judged downs, the baseline every survival rule compares with.
                "active_s": _r(sum(float(rows[j].get("active_s") or 0) for j in others_idx), 4),
                "dead_s": _r(sum(scalars[j]["dead_s"] or 0 for j in others_idx), 4),
                "downs": [_squad_down(f) for f in others_down],
                "party_stab_up": _r(_median(party_stab)) if party_stab else None,
            },
            "peers": peers,
            "spec_peers": spec_peers,
            "dealt": _skill_table((pt.player.raw.get("totalDamageDist") or [[]])[0], names,
                                  taken=False),
            "taken": _skill_table((pt.player.raw.get("totalDamageTaken") or [[]])[0], names,
                                  taken=True),
        }
        _attach_recaps(facts, pt, names)
        out.append({
            "key": pt.key,
            "account": acc,
            "name": pt.player.name,
            "profession": row["profession"],
            "party": int(row["group"] or 0),
            "is_pov": _is_pov(pt, fight.pov_account, fight.pov_name),
            "is_commander": bool(row.get("is_commander")),
            "in_fight": bool(pt.in_fight),
            "active_s": float(row.get("active_s") or 0),
            "facts": facts,
        })
    return out


def _is_pov(pt: PlayerTimeline, pov_account: str, pov_name: str) -> bool:
    p = pt.player
    if pov_account and p.account:
        return p.account == pov_account
    return bool(pov_name) and p.name == pov_name


def _squad_down(f: dict[str, Any]) -> list[Any]:
    """A squad down as a compact tuple: [stab, party stab %, distance to tag, other downs
    within 4 s, died]. Distance -1 when unknown (no tag, or the commander)."""
    return [f["stab"], f["party_stab"], -1 if f["dist_tag"] is None else f["dist_tag"],
            f["near"], int(f["died"])]


def _down_fact(d: dict[str, Any], key: str, by_key: dict[str, PlayerTimeline],
               pts: list[PlayerTimeline], tl: Any, judged: list[tuple[dict, str]],
               judge: bool = True) -> dict[str, Any]:
    pt = by_key[key]
    t = float(d["t"])
    sec = int(math.floor(t))
    n = len(pt.health)
    hp = pt.health[int(np.clip(sec - HP_BEFORE_S, 0, n - 1))] if n else None
    acc = pt.player.account or pt.player.name
    near = sum(1 for e, k in judged
               if abs(float(e["t"]) - t) <= NEAR_DOWN_S
               and (by_key[k].player.account or by_key[k].player.name) != acc)
    # The party's stability just before (the second before the down): share of the other up
    # party members that had any.
    j = int(np.clip(sec - 1, 0, n - 1)) if n else 0
    mates = [q for q in pts if q.in_fight and q.player.group == pt.player.group
             and (q.player.account or q.player.name) != acc]
    up = [q for q in mates if q.up[j]]
    party_stab = round(100 * sum(1 for q in up if q.stab[j] > 0) / len(up)) if up else None
    out = {
        "t": t,
        "stab": int(d["stab"]),
        "party_stab": party_stab,
        "dist_tag": d["dist_tag"],
        "dist_stack": d["dist_stack"],
        "conditions": int(d["conditions"]),
        "boons": int(d["boons"]),
        "died": bool(d["died"]),
        "hp_before": None if hp is None else int(round(float(hp))),
        "near": near,
    }
    if not judge:
        out["left"] = bool(d["left"])
        out["after_calloff"] = d["round"] is None
    return out


def _attach_recaps(facts: dict[str, Any], pt: PlayerTimeline, names: _Names) -> None:
    """Each death recap belongs to the down that ended in that death (down end = death)."""
    recaps = pt.player.raw.get("deathRecap") or []
    intervals = pt.player.down_intervals
    for down in facts["downs"] + facts["downs_left"]:
        if not down["died"]:
            continue
        start = down["t"] * 1000.0
        iv = next((iv for iv in intervals if abs(iv[0] - start) <= 10), None)
        if iv is None:
            continue
        entry = next((r for r in recaps if abs(float(r.get("deathTime") or -1e12) - iv[1])
                      <= 500), None)
        if entry is not None and (rc := _recap(entry, names)):
            down["recap"] = rc
