"""Stat column definitions shared by the stats tables (UI) and the detectors.

Each column knows how to extract a per-player value from EI data and how to aggregate it into a
party / squad row. The frontend renders tables purely from this metadata.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ..model.fight import BOONS, INTENSITY_BOONS, Player

Agg = Literal["sum", "mean", "max"]
Fmt = Literal["int", "num", "pct", "stacks", "dist", "sec", "text"]


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    tab: str
    extract: Callable[[Player], float | str]
    agg: Agg = "sum"
    fmt: Fmt = "int"
    higher_is_better: bool | None = True
    group: str | None = None  # sub-heading inside a tab (e.g. "Uptime", "Squad generation")
    description: str = ""

    def meta(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "tab": self.tab,
            "agg": self.agg,
            "fmt": self.fmt,
            "higherIsBetter": self.higher_is_better,
            "group": self.group,
            "description": self.description,
        }


def _f(section: str, key: str, scale: float = 1.0) -> Callable[[Player], float]:
    def get(p: Player) -> float:
        v = p.first(section).get(key, 0) or 0
        return float(v) * scale

    return get


def _healing(p: Player) -> float:
    ext = p.raw.get("extHealingStats") or {}
    out = (ext.get("outgoingHealing") or [{}])[0]
    return float(out.get("healing", 0) or 0)


def _downed_healing(p: Player) -> float:
    ext = p.raw.get("extHealingStats") or {}
    out = (ext.get("outgoingHealing") or [{}])[0]
    return float(out.get("downedHealing", 0) or 0)


def _barrier(p: Player) -> float:
    ext = p.raw.get("extBarrierStats") or {}
    out = (ext.get("outgoingBarrier") or [{}])[0]
    return float(out.get("barrier", 0) or 0)


def _active_s(p: Player) -> float:
    return p.active_ms / 1000.0


def _uptime(buff_id: int, presence: bool = False) -> Callable[[Player], float]:
    def get(p: Player) -> float:
        b = p.buff(buff_id)
        if not b:
            return 0.0
        data = (b.get("buffData") or [{}])[0]
        return float(data.get("presence" if presence else "uptime", 0) or 0)

    return get


def _generation(buff_id: int, source: str, field: str = "generation"
                ) -> Callable[[Player], float]:
    """EI generation value; for stacking boons 'generationPresence' is the uptime share in %."""
    def get(p: Player) -> float:
        b = p.buff(buff_id, source)
        if not b:
            return 0.0
        return float((b.get("buffData") or [{}])[0].get(field, 0) or 0)

    return get


IDENTITY: list[Column] = [
    Column("name", "Name", "identity", lambda p: p.name, fmt="text", higher_is_better=None),
    Column(
        "account", "Account", "identity", lambda p: p.account, fmt="text", higher_is_better=None
    ),
    Column(
        "profession", "Profession", "identity", lambda p: p.profession, fmt="text",
        higher_is_better=None,
    ),
    Column("group", "Party", "identity", lambda p: p.group, fmt="int", higher_is_better=None),
]

OFFENSE: list[Column] = [
    Column("damage", "Damage", "offense", _f("dpsAll", "damage"), fmt="num"),
    Column("dps", "DPS", "offense", _f("dpsAll", "dps"), fmt="num"),
    Column("power_damage", "Power dmg", "offense", _f("dpsAll", "powerDamage"), fmt="num"),
    Column("condi_damage", "Condi dmg", "offense", _f("dpsAll", "condiDamage"), fmt="num"),
    Column(
        "down_contribution", "Down contrib.", "offense", _f("statsAll", "downContribution"),
        fmt="num", description="Damage dealt to enemies that went down shortly after.",
    ),
    Column(
        "against_downed", "Dmg to downed", "offense", _f("statsAll", "againstDownedDamage"),
        fmt="num", description="Damage dealt to downed enemies (cleaving downs).",
    ),
    Column("downed", "Downs dealt", "offense", _f("statsAll", "downed")),
    Column("killed", "Kills", "offense", _f("statsAll", "killed")),
    Column("cc", "CC applied", "offense", _f("statsAll", "appliedCrowdControl")),
    Column("interrupts", "Interrupts", "offense", _f("statsAll", "interrupts")),
    Column("breakbar", "Breakbar dmg", "offense", _f("dpsAll", "breakbarDamage"), fmt="num"),
]

SUPPORT: list[Column] = [
    Column("strips", "Strips", "support", _f("support", "boonStrips"),
           description="Boons removed from enemies."),
    Column("cleanses", "Cleanses", "support", _f("support", "condiCleanse"),
           description="Conditions removed from allies."),
    Column("cleanses_self", "Self cleanses", "support", _f("support", "condiCleanseSelf")),
    Column("healing", "Healing", "support", _healing, fmt="num",
           description="Outgoing healing (requires the arcdps healing addon)."),
    Column("downed_healing", "Downed healing", "support", _downed_healing, fmt="num"),
    Column("barrier", "Barrier", "support", _barrier, fmt="num"),
    Column("resurrects", "Resurrects", "support", _f("support", "resurrects")),
    Column("res_time", "Res time", "support", _f("support", "resurrectTime"), fmt="sec"),
    Column("stun_breaks", "Stun breaks", "support", _f("support", "stunBreak")),
]

DEFENSE: list[Column] = [
    Column("damage_taken", "Damage taken", "defense", _f("defenses", "damageTaken"), fmt="num",
           higher_is_better=False),
    Column("condi_taken", "Condi taken", "defense", _f("defenses", "conditionDamageTaken"),
           fmt="num", higher_is_better=False),
    Column("barrier_absorbed", "Barrier absorbed", "defense", _f("defenses", "damageBarrier"),
           fmt="num"),
    Column("downs", "Downs", "defense", _f("defenses", "downCount"), higher_is_better=False),
    Column("deaths", "Deaths", "defense", _f("defenses", "deadCount"), higher_is_better=False),
    Column("dodges", "Dodges", "defense", _f("defenses", "dodgeCount")),
    Column("blocks", "Blocks", "defense", _f("defenses", "blockedCount")),
    Column("evades", "Evades", "defense", _f("defenses", "evadedCount")),
    Column("invulned", "Invulned", "defense", _f("defenses", "invulnedCount")),
    Column("incoming_strips", "Boons lost", "defense", _f("defenses", "boonStrips"),
           higher_is_better=False, description="Boons stripped from this player by enemies."),
    Column("incoming_cc", "CC received", "defense", _f("defenses", "receivedCrowdControl"),
           higher_is_better=False),
    Column("avg_conditions", "Avg conditions", "defense", _f("statsAll", "avgConditions"),
           agg="mean", fmt="stacks", higher_is_better=False),
]

POSITIONING: list[Column] = [
    Column("dist_to_com", "Dist. to tag", "positioning", _f("statsAll", "distToCom"),
           agg="mean", fmt="dist", higher_is_better=False,
           description="Average distance to the commander (inches)."),
    Column("stack_dist", "Dist. to stack", "positioning", _f("statsAll", "stackDist"),
           agg="mean", fmt="dist", higher_is_better=False,
           description="Average distance to the squad's center (inches)."),
    Column("active_s", "Active time", "positioning", _active_s, agg="mean", fmt="sec"),
    Column("avg_boons", "Avg boons", "positioning", _f("statsAll", "avgBoons"), agg="mean",
           fmt="stacks"),
]


def _boon_columns() -> list[Column]:
    cols: list[Column] = []
    for bid, name in BOONS.items():
        if bid in INTENSITY_BOONS:
            cols.append(Column(f"up_{bid}", f"{name} %", "boons", _uptime(bid, presence=True),
                               agg="mean", fmt="pct", group="Uptime"))
            cols.append(Column(f"stk_{bid}", f"{name} stacks", "boons", _uptime(bid),
                               agg="mean", fmt="stacks", group="Uptime"))
        else:
            cols.append(Column(f"up_{bid}", name, "boons", _uptime(bid), agg="mean", fmt="pct",
                               group="Uptime"))
    for source, label in [("selfBuffs", "Self"), ("groupBuffs", "Group"),
                          ("offGroupBuffs", "Off-group"), ("squadBuffs", "Squad")]:
        for bid, name in BOONS.items():
            group = f"{label} generation"
            if bid in INTENSITY_BOONS:
                cols.append(Column(
                    f"gen_{source}_{bid}_pct", f"{name} %", "boons",
                    _generation(bid, source, "generationPresence"), agg="sum", fmt="pct",
                    group=group,
                    description=f"Share of time this player's {name.lower()} was on the targets."))
                cols.append(Column(
                    f"gen_{source}_{bid}", f"{name} stacks", "boons", _generation(bid, source),
                    agg="sum", fmt="stacks", group=group,
                    description=f"Average {name.lower()} stacks this player kept on each target."))
            else:
                cols.append(Column(f"gen_{source}_{bid}", name, "boons",
                                   _generation(bid, source), agg="sum", fmt="pct", group=group))
    return cols


BOON_COLUMNS = _boon_columns()
ALL_COLUMNS: list[Column] = IDENTITY + OFFENSE + SUPPORT + DEFENSE + POSITIONING + BOON_COLUMNS
COLUMNS_BY_KEY = {c.key: c for c in ALL_COLUMNS}
