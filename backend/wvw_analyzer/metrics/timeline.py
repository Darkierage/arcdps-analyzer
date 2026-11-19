"""Per-second series, positions and down/death events built from EI timelines."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..model.fight import (
    AEGIS,
    PROTECTION,
    RESISTANCE,
    STABILITY,
    Actor,
    Fight,
    Player,
    interval_mask,
    sample_states,
)
from .rounds import Round, down_left, round_of, split_rounds

NEAR_STACK = 2500.0  # inches from the stack center to count as "with the squad"
REMOTE_DOWN = 5000.0  # downs farther than this from the stack belong to another fight
GVG_ACTIVITY = 0.01  # share of peak per-second damage that still counts as fighting in GvG


def positions_at(actor: Actor, fight: Fight, times_ms: np.ndarray) -> np.ndarray:
    """(N, 2) positions in inches at the given times; NaN where unknown."""
    cr = actor.replay
    pos = cr.get("positions") or []
    out = np.full((len(times_ms), 2), np.nan)
    if not pos:
        return out
    arr = np.asarray(pos, dtype=float) / max(fight.inch_to_pixel, 1e-9)
    start = float(cr.get("start") or 0)
    end = float(cr.get("end") or (start + len(arr) * fight.polling_ms))
    idx = np.rint((times_ms - start) / fight.polling_ms).astype(int)
    valid = (times_ms >= start) & (times_ms <= end) & (idx >= 0) & (idx < len(arr))
    out[valid] = arr[idx[valid]]
    return out


def _cumulative_to_rate(values: list[float] | None, n: int) -> np.ndarray:
    """EI '*1S' arrays are cumulative per second; convert to per-second amounts of length n."""
    if not values:
        return np.zeros(n)
    arr = np.asarray(values, dtype=float)
    rate = np.diff(arr, prepend=0.0)
    if len(rate) >= n:
        return rate[:n]
    return np.pad(rate, (0, n - len(rate)))


def _first_phase(raw: dict[str, Any], key: str) -> list[float] | None:
    v = raw.get(key)
    return v[0] if v else None


@dataclass
class PlayerTimeline:
    player: Player
    alive: np.ndarray  # not dead / disconnected
    up: np.ndarray  # alive and not downed
    stab: np.ndarray  # stability stacks
    resist: np.ndarray
    prot: np.ndarray
    aegis: np.ndarray
    boons: np.ndarray  # number of distinct boons
    conditions: np.ndarray
    health: np.ndarray
    pos: np.ndarray  # (N, 2) inches
    dmg_out: np.ndarray
    dmg_in: np.ndarray
    healing: np.ndarray
    barrier: np.ndarray
    in_fight: bool = True
    near_share: float = 1.0
    fight_dist_tag: float | None = None  # median distance to tag while up, during engagement
    fight_dist_stack: float | None = None


@dataclass
class Timeline:
    t: np.ndarray
    players: list[PlayerTimeline]
    squad: dict[str, np.ndarray] = field(default_factory=dict)
    parties: dict[int, dict[str, np.ndarray]] = field(default_factory=dict)
    squad_downs: list[dict[str, Any]] = field(default_factory=list)
    squad_deaths: list[dict[str, Any]] = field(default_factory=list)
    enemy_downs: list[float] = field(default_factory=list)
    enemy_deaths: list[float] = field(default_factory=list)
    commander_pos: np.ndarray | None = None
    engage_start: float = 0.0
    engage_end: float = 0.0
    allies_near: int = 0
    mode: str = "zerg"
    # One round in zerg mode; GvG logs can hold several, each ending with a call-off.
    rounds: list[Round] = field(default_factory=list)
    # Enemy downs/deaths with GvG bookkeeping: {"t", "round", "left"} / {"t", "round"}.
    enemy_down_events: list[dict[str, Any]] = field(default_factory=list)
    enemy_death_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def gvg(self) -> bool:
        return self.mode == "gvg"

    def series_json(self) -> dict[str, Any]:
        def clean(a: np.ndarray) -> list[float | None]:
            return [None if not np.isfinite(x) else round(float(x), 3) for x in a]

        return {
            "t": self.t.tolist(),
            "squad": {k: clean(v) for k, v in self.squad.items()},
            "parties": {
                str(g): {k: clean(v) for k, v in s.items()} for g, s in self.parties.items()
            },
            "squadDowns": self.squad_downs,
            "squadDeaths": self.squad_deaths,
            "enemyDowns": [round(x, 2) for x in self.enemy_downs],
            "enemyDeaths": [round(x, 2) for x in self.enemy_deaths],
            "engage": [self.engage_start, self.engage_end],
            "mode": self.mode,
            "rounds": [r.json() for r in self.rounds],
            "enemyDownsLeft": [round(e["t"], 2) for e in self.enemy_down_events if e["left"]],
        }


def _player_timeline(p: Player, fight: Fight, times_ms: np.ndarray, n: int) -> PlayerTimeline:
    dead = interval_mask(p.dead_intervals, times_ms)
    dc = interval_mask(p.dc_intervals, times_ms)
    down = interval_mask(p.down_intervals, times_ms)
    alive = ~dead & ~dc
    up = alive & ~down
    ext_h = p.raw.get("extHealingStats") or {}
    ext_b = p.raw.get("extBarrierStats") or {}
    return PlayerTimeline(
        player=p,
        alive=alive,
        up=up,
        stab=sample_states(p.buff_states(STABILITY), times_ms),
        resist=sample_states(p.buff_states(RESISTANCE), times_ms),
        prot=sample_states(p.buff_states(PROTECTION), times_ms),
        aegis=sample_states(p.buff_states(AEGIS), times_ms),
        boons=sample_states(p.raw.get("boonsStates"), times_ms),
        conditions=sample_states(p.raw.get("conditionsStates"), times_ms),
        health=sample_states(p.raw.get("healthPercents"), times_ms, default=100.0),
        pos=positions_at(p, fight, times_ms),
        dmg_out=_cumulative_to_rate(_first_phase(p.raw, "damage1S"), n),
        dmg_in=_cumulative_to_rate(_first_phase(p.raw, "damageTaken1S"), n),
        healing=_cumulative_to_rate(_first_phase(ext_h, "healing1S"), n),
        barrier=_cumulative_to_rate(_first_phase(ext_b, "barrier1S"), n),
    )


def _coverage(pts: list[PlayerTimeline], attr: str) -> np.ndarray:
    """Fraction of up players having the boon, per second (NaN when nobody is up)."""
    if not pts:
        return np.array([])
    up = np.stack([p.up for p in pts])
    has = np.stack([getattr(p, attr) > 0 for p in pts]) & up
    n_up = up.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n_up > 0, has.sum(axis=0) / n_up, np.nan)


def _mean_up(pts: list[PlayerTimeline], attr: str) -> np.ndarray:
    up = np.stack([p.up for p in pts])
    vals = np.stack([getattr(p, attr) for p in pts])
    n_up = up.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n_up > 0, (vals * up).sum(axis=0) / n_up, np.nan)


def _group_series(pts: list[PlayerTimeline]) -> dict[str, np.ndarray]:
    return {
        "up": np.stack([p.up for p in pts]).sum(axis=0).astype(float),
        "downed": np.stack([p.alive & ~p.up for p in pts]).sum(axis=0).astype(float),
        "dead": np.stack([~p.alive for p in pts]).sum(axis=0).astype(float),
        "stab": _coverage(pts, "stab"),
        "resist": _coverage(pts, "resist"),
        "prot": _coverage(pts, "prot"),
        "aegis": _coverage(pts, "aegis"),
        "boons": _mean_up(pts, "boons"),
        "conditions": _mean_up(pts, "conditions"),
        "health": _mean_up(pts, "health"),
        "dmg_out": np.stack([p.dmg_out for p in pts]).sum(axis=0),
        "dmg_in": np.stack([p.dmg_in for p in pts]).sum(axis=0),
        "healing": np.stack([p.healing for p in pts]).sum(axis=0),
        "barrier": np.stack([p.barrier for p in pts]).sum(axis=0),
    }



def build_timeline(fight: Fight, mode: str = "zerg", round_gap_s: float = 25.0,
                   calloff_grace_s: float = 3.0) -> Timeline:
    t = fight.time_grid()
    times_ms = t * 1000.0
    n = len(t)
    pts = [_player_timeline(p, fight, times_ms, n) for p in fight.squad]
    tl = Timeline(t=t, players=pts, mode=mode)
    if not pts:
        return tl

    cmd = fight.commander
    if cmd is not None:
        tl.commander_pos = positions_at(cmd, fight, times_ms)

    # Stack center = median position of up players; distances per player per second.
    pos = np.stack([p.pos for p in pts])  # (P, N, 2)
    up = np.stack([p.up for p in pts])
    masked = np.where(up[..., None], pos, np.nan)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices when nobody is up
        center = np.nanmedian(masked, axis=0)  # (N, 2)
        d_center = np.linalg.norm(masked - center[None], axis=2)  # (P, N)
        d_tag = (np.linalg.norm(masked - tl.commander_pos[None], axis=2)
                 if tl.commander_pos is not None else None)

    # Engagement window: from first to last second with meaningful damage either way.
    dmg_out = np.stack([p.dmg_out for p in pts]).sum(axis=0)
    dmg_in = np.stack([p.dmg_in for p in pts]).sum(axis=0)
    activity = dmg_out + dmg_in
    thresh = max(activity.max() * 0.05, 1.0)
    active_idx = np.nonzero(activity >= thresh)[0]
    if len(active_idx):
        tl.engage_start, tl.engage_end = float(t[active_idx[0]]), float(t[active_idx[-1]])
    else:
        tl.engage_start, tl.engage_end = 0.0, float(t[-1])

    # Who actually took part: near the stack for a meaningful share of the engagement, or
    # dealt/took damage. Squad members elsewhere on the map are excluded from fight series.
    e0, e1 = int(tl.engage_start), int(tl.engage_end) + 1
    for i, p in enumerate(pts):
        seen = np.isfinite(d_center[i, e0:e1])
        near = (d_center[i, e0:e1] <= NEAR_STACK) & seen
        p.near_share = float(near.sum() / max(seen.sum(), 1))
        busy = bool((p.dmg_out[e0:e1].sum() + p.dmg_in[e0:e1].sum()) > 0)
        p.in_fight = bool(p.near_share >= 0.3 or (busy and p.near_share >= 0.1) or (
            busy and not seen.any()))
        # Typical distances while actually around the fight (excludes running back from spawn).
        local = seen & (d_center[i, e0:e1] <= REMOTE_DOWN)
        if local.any():
            if d_tag is not None and not p.player.is_commander:
                v = np.nanmedian(d_tag[i, e0:e1][local])
                p.fight_dist_tag = None if np.isnan(v) else float(v)
            p.fight_dist_stack = float(np.nanmedian(d_center[i, e0:e1][local]))

    # Non-squad allies count only if they were around the fight (not elsewhere on the map).
    for ally in fight.allies:
        apos = positions_at(ally, fight, times_ms)[e0:e1]
        with np.errstate(all="ignore"):
            d = np.linalg.norm(apos - center[e0:e1], axis=1)
        seen_a = np.isfinite(d)
        if seen_a.any() and (d[seen_a] <= NEAR_STACK).mean() >= 0.3:
            tl.allies_near += 1

    fighting = [p for p in pts if p.in_fight] or pts
    tl.squad = _group_series(fighting)
    if tl.gvg:
        # After a call-off nobody deals damage at all, so any real fighting (even the low-level
        # finishing of downs at the end of a round) still belongs to the round. Only players at
        # the fight count: a scout skirmishing elsewhere must not hide the call-off.
        act = tl.squad["dmg_out"] + tl.squad["dmg_in"]
        busy = act >= max(act.max() * GVG_ACTIVITY, 1.0)
        tl.rounds = split_rounds(busy, t, round_gap_s, calloff_grace_s)
    else:  # one open-ended round: nothing is ever "after the call-off"
        tl.rounds = [Round(tl.engage_start, tl.engage_end, float(t[-1]) + 1.0)]
    for g in fight.parties:
        members = [p for p in fighting if p.player.group == g]
        if members:
            tl.parties[g] = _group_series(members)

    fi = np.array([p.in_fight for p in pts])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        tl.squad["dist_stack"] = np.nanmedian(d_center[fi], axis=0)
        if d_tag is not None:
            tl.squad["dist_tag"] = np.nanmedian(d_tag[fi], axis=0)

    _collect_events(fight, tl, center)
    return tl


def _collect_events(fight: Fight, tl: Timeline, center: np.ndarray) -> None:
    for pt in tl.players:
        p = pt.player
        dead_starts = [s for s, _ in p.dead_intervals]
        for s, e in p.down_intervals:
            if not pt.in_fight:
                continue
            ts = s / 1000.0
            before = np.array([max(s - 250.0, 0.0)])
            ppos = positions_at(p, fight, np.array([s]))[0]
            d_tag = d_center = None
            if tl.commander_pos is not None and not p.is_commander:
                cpos = positions_at(fight.commander, fight, np.array([s]))[0]  # type: ignore[arg-type]
                if np.all(np.isfinite(cpos)) and np.all(np.isfinite(ppos)):
                    d_tag = float(np.linalg.norm(ppos - cpos))
            c = center[int(np.clip(np.floor(ts), 0, len(center) - 1))]
            if np.all(np.isfinite(c)) and np.all(np.isfinite(ppos)):
                d_center = float(np.linalg.norm(ppos - c))
            if d_center is not None and d_center > REMOTE_DOWN:
                continue  # went down somewhere else on the map, not part of this fight
            tl.squad_downs.append({
                "t": round(ts, 2),
                "round": round_of(ts, tl.rounds),
                "left": tl.gvg and down_left(ts, e / 1000.0, tl.rounds),
                "player": p.name,
                "profession": p.profession,
                "group": p.group,
                "died": any(abs(ds - e) <= 300 for ds in dead_starts),
                "stab": float(sample_states(p.buff_states(STABILITY), before)[0]),
                "resist": float(sample_states(p.buff_states(RESISTANCE), before)[0]) > 0,
                "boons": float(sample_states(p.raw.get("boonsStates"), before)[0]),
                "conditions": float(sample_states(p.raw.get("conditionsStates"), before)[0]),
                "dist_tag": None if d_tag is None else round(d_tag),
                "dist_stack": None if d_center is None else round(d_center),
            })
        if pt.in_fight:
            for s, _ in p.dead_intervals:
                tl.squad_deaths.append(
                    {"t": round(s / 1000.0, 2), "player": p.name, "group": p.group,
                     "round": round_of(s / 1000.0, tl.rounds)})
    tl.squad_downs.sort(key=lambda e: e["t"])
    tl.squad_deaths.sort(key=lambda e: e["t"])
    for en in fight.enemies:
        for s, e in en.down_intervals:
            ts = s / 1000.0
            tl.enemy_downs.append(ts)
            tl.enemy_down_events.append({"t": ts, "round": round_of(ts, tl.rounds),
                                         "left": tl.gvg and down_left(ts, e / 1000.0, tl.rounds)})
        for s, _ in en.dead_intervals:
            tl.enemy_deaths.append(s / 1000.0)
            tl.enemy_death_events.append({"t": s / 1000.0,
                                          "round": round_of(s / 1000.0, tl.rounds)})
    tl.enemy_downs.sort()
    tl.enemy_deaths.sort()
    tl.enemy_down_events.sort(key=lambda e: e["t"])
    tl.enemy_death_events.sort(key=lambda e: e["t"])
