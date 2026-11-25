"""One player's stored facts, as one view per fight.

`player_fights` holds one row per Elite Insights row. For the review a player is one player in
one fight: a split player's in-fight rows are merged (counts add up, as in the session
aggregate), and when two logs cover the same fight (a friend's log imported next to your own)
only one is kept, the one where the player recorded.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Two logs whose time spans overlap by this share of the shorter one are the same fight.
SAME_FIGHT_OVERLAP = 0.5


@dataclass
class FightView:
    fight_id: int
    start: str | None
    start_ts: float | None  # epoch seconds, None when the log has no readable start
    dur_s: float
    session_id: int | None
    rows: list[dict[str, Any]]  # this account's in-fight rows: identity columns + "facts"
    mode: str = "zerg"
    result: str | None = None
    map: str | None = None
    downs: list[dict[str, Any]] = field(default_factory=list)  # judged downs, with "key"
    squad_downs: list[dict[str, Any]] = field(default_factory=list)  # the rest of the squad's

    @property
    def main(self) -> dict[str, Any]:
        """The longest in-fight row (its party, peers and skills stand for the fight)."""
        return max(self.rows, key=lambda r: (r["active_s"] or 0, r["key"] == r["account"]))

    @property
    def facts(self) -> dict[str, Any]:
        return self.main["facts"]

    @property
    def active_s(self) -> float:
        return float(sum(r["active_s"] or 0 for r in self.rows))

    @property
    def dead_s(self) -> float:
        return float(sum(r["facts"].get("dead_s") or 0 for r in self.rows))

    @property
    def commander(self) -> bool:
        return any(r["is_commander"] for r in self.rows)

    @property
    def pov(self) -> bool:
        return any(r["is_pov"] for r in self.rows)

    @property
    def squad(self) -> dict[str, Any]:
        return self.facts["squad"]

    @property
    def first_rank(self) -> int | None:
        return self.facts.get("first_rank")

    def flag(self, name: str) -> bool | None:
        """food / utility: True if any row had it, None if no row's log lists consumables."""
        vals = [r["facts"].get(name) for r in self.rows]
        if any(v is True for v in vals):
            return True
        return False if any(v is False for v in vals) else None

    def spec_rows(self) -> dict[str, dict[str, Any]]:
        """The longest row per elite spec (output and activity are judged per spec)."""
        out: dict[str, dict[str, Any]] = {}
        for r in sorted(self.rows, key=lambda r: -(r["active_s"] or 0)):
            out.setdefault(r["profession"], r)
        return out

    @property
    def specs(self) -> list[str]:
        return list(self.spec_rows())


def _ts(start: str | None) -> float | None:
    if not start:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(start, fmt).timestamp()
        except ValueError:
            continue
    return None


def _squad_down(x: list[Any]) -> dict[str, Any]:
    stab, party_stab, dist_tag, near, died = x
    return {"stab": stab, "party_stab": party_stab, "dist_tag": None if dist_tag < 0 else dist_tag,
            "near": near, "died": bool(died)}


def build_views(rows: list[dict[str, Any]], fights: dict[int, dict[str, Any]]
                ) -> list[FightView]:
    """Views of one account's fights, oldest first. `rows` are its `player_fights` rows with
    unpacked facts; `fights` gives each fight's start, duration, session, mode, result, map."""
    by_fight: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        if r["in_fight"]:
            by_fight.setdefault(r["fight_id"], []).append(r)
    views = []
    for fid, rs in by_fight.items():
        f = fights.get(fid) or {}
        v = FightView(fight_id=fid, start=f.get("start"), start_ts=_ts(f.get("start")),
                      dur_s=float(f.get("dur_s") or rs[0]["facts"].get("dur_s") or 0),
                      session_id=f.get("session_id"), rows=rs,
                      mode=f.get("mode") or rs[0]["facts"].get("mode") or "zerg",
                      result=f.get("result"), map=f.get("map"))
        v.downs = sorted(({**d, "key": r["key"]} for r in rs for d in r["facts"]["downs"]),
                         key=lambda d: d["t"])
        v.squad_downs = [_squad_down(x) for x in v.squad["downs"]]
        views.append(v)
    views.sort(key=lambda v: (v.start_ts if v.start_ts is not None else float("inf"),
                              v.fight_id))
    return dedupe(views)


def dedupe(views: list[FightView]) -> list[FightView]:
    """Keep one view per real fight: two logs of the same fight overlap in time. The one the
    player recorded wins, then the longer time in the fight, then the earlier import."""
    kept: list[FightView] = []
    for v in views:
        clash = next((k for k in kept if _same_fight(k, v)), None)
        if clash is None:
            kept.append(v)
        elif _rank(v) < _rank(clash):
            kept[kept.index(clash)] = v
    return kept


def _rank(v: FightView) -> tuple:
    return (not v.pov, -v.active_s, v.fight_id)


def _same_fight(a: FightView, b: FightView) -> bool:
    if a.start_ts is None or b.start_ts is None:
        return False
    lo = max(a.start_ts, b.start_ts)
    hi = min(a.start_ts + a.dur_s, b.start_ts + b.dur_s)
    shorter = min(a.dur_s, b.dur_s)
    return shorter > 0 and (hi - lo) >= SAME_FIGHT_OVERLAP * shorter


def majority(values: list[Any]) -> Any:
    """The most common value; None on a tie for first (no clear majority)."""
    common = Counter(values).most_common(2)
    if not common or (len(common) > 1 and common[0][1] == common[1][1]):
        return None
    return common[0][0]
