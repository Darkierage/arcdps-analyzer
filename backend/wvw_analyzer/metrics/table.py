"""Per-player stat rows and party / squad aggregation."""

from __future__ import annotations

from typing import Any

from ..model.fight import Fight
from .columns import ALL_COLUMNS, Column

Row = dict[str, Any]


def player_rows(fight: Fight) -> list[Row]:
    rows = []
    for p in fight.squad:
        row: Row = {c.key: c.extract(p) for c in ALL_COLUMNS}
        row["is_commander"] = p.is_commander
        row["has_heal_data"] = p.has_heal_data
        rows.append(row)
    return rows


def _aggregate(rows: list[Row], columns: list[Column]) -> Row:
    out: Row = {}
    n = len(rows)
    for c in columns:
        if c.fmt == "text" or c.key == "group":
            continue
        values = [float(r.get(c.key) or 0) for r in rows]
        if not values:
            out[c.key] = 0.0
        elif c.agg == "sum":
            out[c.key] = sum(values)
        elif c.agg == "max":
            out[c.key] = max(values)
        else:
            out[c.key] = sum(values) / n
    out["members"] = n
    return out


def party_rows(rows: list[Row]) -> list[Row]:
    groups = sorted({r["group"] for r in rows})
    out = []
    for g in groups:
        members = [r for r in rows if r["group"] == g]
        agg = _aggregate(members, ALL_COLUMNS)
        agg.update(name=f"Party {g}", group=g, profession="", account="")
        agg["professions"] = sorted(r["profession"] for r in members)
        out.append(agg)
    return out


def squad_row(rows: list[Row]) -> Row:
    agg = _aggregate(rows, ALL_COLUMNS)
    agg.update(name="Squad", group=0, profession="", account="")
    return agg
