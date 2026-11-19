"""Fight-level summary (counts, outcome) and the Metrics bundle."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from ..config import GvgSettings
from ..model.fight import Fight
from .columns import ALL_COLUMNS
from .table import Row, party_rows, player_rows, squad_row
from .timeline import Timeline, build_timeline

Result = Literal["win", "loss", "even", "skirmish"]


def classify_result(squad_deaths: int, enemy_deaths: int) -> Result:
    """Outcome from the deaths trade, as seen from the recording player's view."""
    if squad_deaths + enemy_deaths < 3:
        return "skirmish"
    ratio = (enemy_deaths + 1) / (squad_deaths + 1)
    if ratio >= 1.5:
        return "win"
    if ratio <= 1 / 1.5:
        return "loss"
    return "even"


def classify_round(squad_out: int, enemy_out: int) -> Result:
    """GvG round result from players taken out (counted deaths + downs left at the call-off).

    There is no "skirmish" in GvG: every round is a deliberate fight.
    """
    ratio = (enemy_out + 1) / (squad_out + 1)
    if ratio >= 1.5:
        return "win"
    if ratio <= 1 / 1.5:
        return "loss"
    return "even"


def gvg_summary(tl: Timeline) -> dict[str, Any]:
    """Per-round bookkeeping for GvG: what was left at each call-off and who won the round."""
    rounds = []
    for i, r in enumerate(tl.rounds):
        sq_deaths = sum(1 for e in tl.squad_deaths if e["round"] == i)
        en_deaths = sum(1 for e in tl.enemy_death_events if e["round"] == i)
        sq_left = sum(1 for e in tl.squad_downs if e["round"] == i and e["left"])
        en_left = sum(1 for e in tl.enemy_down_events if e["round"] == i and e["left"])
        rounds.append({
            "start": r.start, "calloff": r.calloff,
            "squadDeaths": sq_deaths, "enemyDeaths": en_deaths,
            "squadLeft": sq_left, "enemyLeft": en_left,
            "result": classify_round(sq_deaths + sq_left, en_deaths + en_left),
        })
    wins = sum(1 for r in rounds if r["result"] == "win")
    losses = sum(1 for r in rounds if r["result"] == "loss")
    return {
        "rounds": rounds,
        "roundWins": wins,
        "roundLosses": losses,
        "squadDownsLeft": sum(1 for e in tl.squad_downs if e["left"]),
        "enemyDownsLeft": sum(1 for e in tl.enemy_down_events if e["left"]),
        "squadDownsLate": sum(1 for e in tl.squad_downs if e["round"] is None),
        "enemyDownsLate": sum(1 for e in tl.enemy_down_events if e["round"] is None),
        "squadDeathsLate": sum(1 for e in tl.squad_deaths if e["round"] is None),
        "enemyDeathsLate": sum(1 for e in tl.enemy_death_events if e["round"] is None),
        "result": "win" if wins > losses else "loss" if losses > wins else "even",
    }


@dataclass
class Metrics:
    fight: Fight
    players: list[Row]
    parties: list[Row]
    squad: Row
    timeline: Timeline
    summary: dict[str, Any]

    def player(self, name: str) -> Row | None:
        return next((r for r in self.players if r["name"] == name), None)

    @property
    def active_players(self) -> list[Row]:
        """Squad members that actually took part in the fight."""
        return [r for r in self.players if r.get("in_fight", True)]

    @property
    def active_parties(self) -> list[Row]:
        return party_rows(self.active_players)

    def stats_json(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "columns": [c.meta() for c in ALL_COLUMNS],
            "players": self.players,
            "parties": self.parties,
            "squad": self.squad,
            "timeline": self.timeline.series_json(),
            "enemies": enemy_breakdown(self.fight),
        }


def enemy_breakdown(fight: Fight) -> dict[str, Any]:
    profs = Counter(e.profession for e in fight.enemies)
    return {
        "count": len(fight.enemies),
        "professions": [{"profession": k, "count": v} for k, v in profs.most_common()],
        "teams": sorted({e.team_id for e in fight.enemies}),
    }


def build_summary(fight: Fight, players: list[Row], tl: Timeline) -> dict[str, Any]:
    squad_deaths = int(sum(r["deaths"] for r in players))
    squad_downs = int(sum(r["downs"] for r in players))
    enemy_deaths = sum(e.deaths for e in fight.enemies)
    enemy_downs = sum(e.downs for e in fight.enemies)
    cmd = fight.commander
    in_fight = sum(1 for r in players if r.get("in_fight", True))
    friendly = in_fight + tl.allies_near
    return {
        "logId": fight.log_id,
        "map": fight.map_name,
        "start": fight.start_time,
        "durationS": round(fight.duration_s, 1),
        "squadCount": len(fight.squad),
        "squadInFight": in_fight,
        "allyCount": tl.allies_near,
        "allyTotal": len(fight.allies),
        "enemyCount": len(fight.enemies),
        "outnumberRatio": round(len(fight.enemies) / friendly, 2) if friendly else None,
        "squadDowns": squad_downs,
        "squadDeaths": squad_deaths,
        "enemyDowns": enemy_downs,
        "enemyDeaths": enemy_deaths,
        "squadDamage": float(sum(r["damage"] for r in players)),
        "squadDamageTaken": float(sum(r["damage_taken"] for r in players)),
        "squadStrips": float(sum(r["strips"] for r in players)),
        "squadCleanses": float(sum(r["cleanses"] for r in players)),
        "squadBoonsLost": float(sum(r["incoming_strips"] for r in players)),
        "squadHealing": float(sum(r["healing"] for r in players)),
        "hasHealData": fight.has_heal_data,
        "commander": cmd.name if cmd else None,
        "pov": fight.pov_name,
        "povAccount": fight.pov_account,
        "eiVersion": fight.ei_version,
        "result": classify_result(squad_deaths, enemy_deaths),
        "engage": [tl.engage_start, tl.engage_end],
        # Time actually spent fighting (GvG: without the regroups between rounds).
        "fightS": round(sum(r.calloff - r.start for r in tl.rounds), 1)
        if tl.gvg else tl.engage_end - tl.engage_start,
        "parties": fight.parties,
        "mode": tl.mode,
        # Zerg values; GvG overrides them below. Detectors subtract these from the totals.
        "squadDownsLeft": 0, "enemyDownsLeft": 0, "squadDownsLate": 0, "enemyDownsLate": 0,
        "squadDeathsLate": 0, "enemyDeathsLate": 0,
    }


def compute_metrics(fight: Fight, mode: str = "zerg", gvg: GvgSettings | None = None) -> Metrics:
    gvg = gvg or GvgSettings()
    players = player_rows(fight)
    tl = build_timeline(fight, mode, gvg.round_gap_s, gvg.calloff_grace_s)
    for row, pt in zip(players, tl.players, strict=True):
        row["in_fight"] = pt.in_fight
        row["near_share"] = round(pt.near_share, 2)
        row["fight_dist_tag"] = None if pt.fight_dist_tag is None else round(pt.fight_dist_tag)
        row["fight_dist_stack"] = (
            None if pt.fight_dist_stack is None else round(pt.fight_dist_stack))
    summary = build_summary(fight, players, tl)
    if tl.gvg:
        summary.update(gvg_summary(tl))
    return Metrics(
        fight=fight,
        players=players,
        parties=party_rows(players),
        squad=squad_row(players),
        timeline=tl,
        summary=summary,
    )
