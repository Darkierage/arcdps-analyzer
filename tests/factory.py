"""Build small synthetic Elite Insights JSON documents for tests (no personal data)."""

from __future__ import annotations

from typing import Any

POLL = 300  # ms between combat replay positions
PX = 0.01  # inchToPixel: 1 px = 100 inches


def _stats(**kw: Any) -> list[dict[str, Any]]:
    return [kw]


def player(
    name: str,
    group: int,
    *,
    profession: str = "Firebrand",
    duration_ms: int = 60_000,
    pos_inches: tuple[float, float] = (0.0, 0.0),
    stab: list[list[float]] | None = None,
    downs: list[list[float]] | None = None,
    deaths: list[list[float]] | None = None,
    commander: bool = False,
    damage_per_s: float = 1000.0,
    strips: int = 0,
    cleanses: int = 0,
    boons_lost: int = 0,
    team: int = 1,
    not_in_squad: bool = False,
    boons_states: list[list[float]] | None = None,
    active: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """``active`` = (start_s, end_s) windows with damage dealt/taken; default the whole log."""
    n = duration_ms // POLL + 1
    pos = [[pos_inches[0] * PX, pos_inches[1] * PX]] * n
    secs = duration_ms // 1000 + 1
    if active is None:
        dmg = [int(i * damage_per_s) for i in range(secs)]
    else:  # cumulative damage that only grows inside the active windows
        dmg, total = [], 0.0
        for i in range(secs):
            if any(a < i <= b for a, b in active):
                total += damage_per_s
            dmg.append(int(total))
    downs = downs or []
    deaths = deaths or []
    return {
        "name": name,
        "account": f"{name.replace(' ', '')}.1234",
        "profession": profession,
        "group": group,
        "teamID": team,
        "notInSquad": not_in_squad,
        "isFake": False,
        "hasCommanderTag": commander,
        "commanderTagStates": [[0, duration_ms]] if commander else [],
        "activeTimes": [duration_ms],
        "buffUptimes": [
            {"id": 1122, "buffData": [{"uptime": 1.0, "presence": 50.0}],
             "states": stab if stab is not None else [[0, 0]]},
        ],
        "squadBuffs": [{"id": 1122, "buffData": [{"generation": 0.5}]}],
        "boonsStates": boons_states or [[0, 6]],
        "conditionsStates": [[0, 1]],
        "healthPercents": [[0, 100]],
        "damage1S": [dmg],
        "damageTaken1S": [dmg],
        "dpsAll": _stats(damage=dmg[-1], dps=damage_per_s, powerDamage=dmg[-1], condiDamage=0),
        "statsAll": _stats(distToCom=100, stackDist=100, downContribution=0, killed=0, downed=0,
                           againstDownedDamage=0, avgBoons=6, avgConditions=1),
        "support": _stats(boonStrips=strips, condiCleanse=cleanses, condiCleanseSelf=0,
                          resurrects=0, resurrectTime=0, stunBreak=0),
        "defenses": _stats(damageTaken=dmg[-1], downCount=len(downs), deadCount=len(deaths),
                           boonStrips=boons_lost, conditionDamageTaken=0, damageBarrier=0),
        "combatReplayData": {"start": 0, "end": duration_ms, "positions": pos,
                             "down": downs, "dead": deaths,
                             "dc": [[-(2 ** 63), 0], [duration_ms, 2 ** 63 - 1]]},
    }


def enemy(i: int, *, deaths: int = 0, downs: int = 0, spec: str = "Scourge",
          down_iv: list[list[float]] | None = None,
          dead_iv: list[list[float]] | None = None) -> dict[str, Any]:
    """Enemy with ``downs``/``deaths`` at fixed times, or explicit ms intervals."""
    if down_iv is not None or dead_iv is not None:
        down_iv, dead_iv = down_iv or [], dead_iv or []
        downs, deaths = len(down_iv), len(dead_iv)
    return {
        "name": f"{spec} pl-{1000 + i}",
        "enemyPlayer": True,
        "isFake": False,
        "teamID": 2,
        "defenses": [{"deadCount": deaths, "downCount": downs}],
        "combatReplayData": {"start": 0, "end": 60_000, "positions": [[1, 1]],
                             "down": down_iv if down_iv is not None
                             else [[10_000 + i * 100, 11_000]] * downs,
                             "dead": dead_iv if dead_iv is not None
                             else [[11_000 + i * 100, 60_000]] * deaths},
    }


def fight(players: list[dict[str, Any]], enemies: list[dict[str, Any]],
          duration_ms: int = 60_000) -> dict[str, Any]:
    return {
        "fightName": "Detailed  Seared Borderlands",
        "detailedWvW": True,
        "wvWMapData": {},
        "timeStartStd": "2026-11-17 20:00:00 +01:00",
        "durationMS": duration_ms,
        "recordedBy": players[0]["name"] if players else "",
        "recordedAccountBy": "",
        "eliteInsightsVersion": "test",
        "combatReplayMetaData": {"pollingRate": POLL, "inchToPixel": PX},
        "players": players,
        "targets": enemies,
        "usedExtensions": [],
    }


def zerg(n: int = 10, *, stab_states: list[list[float]] | None = None,
         downs_at: list[float] | None = None, enemies: int = 20, **kw: Any) -> dict[str, Any]:
    """A simple squad in one blob (2 parties); downs_at = seconds at which players go down."""
    downs_at = downs_at or []
    players = []
    for i in range(n):
        down = [[downs_at[i] * 1000, downs_at[i] * 1000 + 2000]] if i < len(downs_at) else []
        dead = [[downs_at[i] * 1000 + 2000, 60_000]] if i < len(downs_at) else []
        players.append(player(f"Player {i}", 1 + i % 2, stab=stab_states, downs=down,
                              deaths=dead, commander=(i == 0), pos_inches=(i * 10.0, 0.0), **kw))
    return fight(players, [enemy(j) for j in range(enemies)])
