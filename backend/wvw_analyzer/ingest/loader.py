"""Load Elite Insights JSON (.json / .json.gz) into the Fight model."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from ..model.fight import Actor, Enemy, Fight, Player


def read_ei_json(path: Path) -> dict[str, Any]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def is_wvw(d: dict[str, Any]) -> bool:
    name = d.get("fightName") or ""
    return bool(
        d.get("detailedWvW")
        or d.get("wvWMapData")
        or "World vs World" in name
        or "WvW" in name
        or "Borderlands" in name
    )


def clean_map_name(fight_name: str) -> str:
    name = re.sub(r"^\s*Detailed\s+", "", fight_name or "")
    name = re.sub(r"^(WvW|World vs World)\s*-\s*", "", name.strip())
    return re.sub(r"\s+", " ", name).strip() or "Unknown map"


def _profession_from_name(name: str) -> str:
    # Enemy players are anonymized as "<Spec> pl-1234".
    return name.split(" pl-")[0] if " pl-" in name else name


def _tag_ms(raw: dict[str, Any]) -> float:
    return float(sum(max(0, e - s) for s, e in raw.get("commanderTagStates") or []))


def load_fight(d: dict[str, Any], log_id: str = "") -> Fight:
    heal_runners: set[str] = set()
    for ext in d.get("usedExtensions") or []:
        if "Healing" in (ext.get("name") or ""):
            heal_runners.update(ext.get("runningExtension") or [])

    squad: list[Player] = []
    squad_teams: set[int] = set()
    for p in d.get("players") or []:
        if p.get("notInSquad") or p.get("isFake"):
            continue
        active = p.get("activeTimes") or [0]
        player = Player(
            name=p.get("name", "?"),
            profession=p.get("profession") or "Unknown",
            team_id=int(p.get("teamID") or 0),
            raw=p,
            account=p.get("account", ""),
            group=int(p.get("group") or 0),
            is_commander=bool(p.get("hasCommanderTag")),
            tag_ms=_tag_ms(p),
            active_ms=float(active[0] if active else 0),
            has_heal_data=p.get("name") in heal_runners,
        )
        squad.append(player)
        squad_teams.add(player.team_id)

    allies = [
        Actor(name=p.get("name", "?"), profession=p.get("profession") or "Unknown",
              team_id=int(p.get("teamID") or 0), raw=p)
        for p in d.get("players") or []
        if p.get("notInSquad") and not p.get("isFake") and int(p.get("teamID") or 0) in squad_teams
    ]

    enemies: list[Enemy] = []
    for t in d.get("targets") or []:
        if not t.get("enemyPlayer") or t.get("isFake"):
            continue
        defenses = (t.get("defenses") or [{}])[0]
        enemies.append(
            Enemy(
                name=t.get("name", "?"),
                profession=_profession_from_name(t.get("name", "?")),
                team_id=int(t.get("teamID") or 0),
                raw=t,
                deaths=int(defenses.get("deadCount") or 0),
                downs=int(defenses.get("downCount") or 0),
            )
        )

    meta = d.get("combatReplayMetaData") or {}
    return Fight(
        log_id=log_id,
        map_name=clean_map_name(d.get("fightName", "")),
        start_time=d.get("timeStartStd") or d.get("timeStart") or "",
        duration_ms=int(d.get("durationMS") or 0),
        pov_name=d.get("recordedBy", ""),
        pov_account=d.get("recordedAccountBy", ""),
        ei_version=d.get("eliteInsightsVersion", ""),
        polling_ms=float(meta.get("pollingRate") or 150),
        inch_to_pixel=float(meta.get("inchToPixel") or 1.0),
        squad=squad,
        allies=allies,
        enemies=enemies,
        raw=d,
    )


def load_fight_file(path: Path) -> Fight:
    log_id = path.name.split("_")[0]
    return load_fight(read_ei_json(path), log_id=log_id)
