"""The personal rules. Each compares the player with a baseline from the same fights.

- Survival (downs and their causes): the rest of the squad in the same fights. A share of
  downs is never judged on its own: a rule fires only when the player's count is well above
  what the squad's rate in those fights predicts *and* unlikely by chance.
- Output and activity: players with the same elite spec and the same job in the same fight
  (same spec is not same job), per spec.
- Positioning and CC: the squad median in the same fights.
"""

from __future__ import annotations

import statistics
from typing import Any

from .base import Outcome, Rule, Scope, pct
from .data import FightView, majority
from .stats import binom_sf, poisson_binomial_sf, poisson_cdf, poisson_sf

JOB_TXT = {"damage": "damage", "strips": "strips", "cleanses": "cleanses",
           "healing": "healing", "stab": "stability given"}
JOB_METRIC = {"damage": "damage", "strips": "strips", "cleanses": "cleanses",
              "healing": "healing", "stab": "stab"}  # job -> its metric in the facts' peers


def _ex(v: FightView, t: float | None = None) -> dict[str, Any]:
    return {"fightId": v.fight_id, "t": t, "start": v.start}


def _recent_first(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(examples, key=lambda e: (e.get("start") or "", e.get("t") or 0), reverse=True)


# ---- survival -------------------------------------------------------------------------------


class DownRate(Rule):
    name = "me_deaths"
    trend_margin = 0.25  # downs per 10 minutes, and at least this share of the earlier value
    label = "Going down more than the squad"
    description = ("Your downs per minute in the fight against the rest of the squad's in the "
                   "same fights. Positive when clearly below.")
    defaults = {
        "min_fights": 5,
        "min_expected": 3,  # your downs or the squad's rate's for you, before judging
        "ratio": 1.5,  # at least this many times the squad's rate ...
        "alpha": 0.05,  # ... and this unlikely at the squad's rate
    }

    def _counts(self, views: list[FightView]) -> dict[str, Any]:
        c = {"obs": 0, "exp": 0.0, "deaths": 0, "dead": 0.0, "sq_dead": 0.0, "active": 0.0,
             "examples": []}
        for v in views:
            sa = float(v.squad.get("active_s") or 0)
            if sa <= 0:
                continue
            a = v.active_s
            c["obs"] += len(v.downs)
            c["deaths"] += sum(1 for d in v.downs if d["died"])
            c["exp"] += a * len(v.squad_downs) / sa
            c["dead"] += v.dead_s
            c["sq_dead"] += a * float(v.squad.get("dead_s") or 0) / sa
            c["active"] += a
            c["examples"] += [_ex(v, d["t"]) for d in v.downs]
        return c

    def _passes(self, views: list[FightView], c: dict[str, Any], scope: Scope) -> bool:
        # Enough to judge: your downs or the squad's rate for your time reach the minimum
        # (a squad that never goes down still makes 10 downs of yours stand out).
        return (len(views) >= self.gate("min_fights", scope)
                and max(c["obs"], c["exp"]) >= self.gate("min_expected", scope))

    def _fires(self, c: dict[str, Any]) -> bool:
        return (c["obs"] >= self.cfg["ratio"] * c["exp"]
                and poisson_sf(c["obs"], c["exp"]) <= self.cfg["alpha"])

    @staticmethod
    def by_spec(views: list[FightView]) -> dict[str, list[FightView]]:
        """Fights by the spec played in them (the main row's)."""
        out: dict[str, list[FightView]] = {}
        for v in views:
            out.setdefault(v.main["profession"], []).append(v)
        return dict(sorted(out.items()))

    def measure(self, views, scope, spec=None):
        if spec is not None:
            views = self.by_spec(views).get(spec, [])
        c = self._counts(views)
        # Your downs per 10 minutes beyond what the squad's rate predicts (a difference, not a
        # ratio: stays finite for a squad that never goes down).
        if not self._passes(views, c, scope):
            return None
        return (c["obs"] - c["exp"]) / max(c["active"], 1.0) * 600

    def _evidence(self, c: dict[str, Any], spec: str | None) -> dict[str, Any]:
        obs, exp, act = c["obs"], c["exp"], max(c["active"], 1.0)
        return {
            "downs": obs, "deaths": c["deaths"],
            "expected": round(exp, 1),
            "per10": round(obs / act * 600, 1), "squad_per10": round(exp / act * 600, 1),
            "ratio": round(obs / max(exp, 0.1), 1),
            "dead_pct": pct(c["dead"] / act), "squad_dead_pct": pct(c["sq_dead"] / act),
            "on_spec": f" on {spec}" if spec else "",
            "spec_txt": "", "causes_txt": "",
        }

    def run(self, views: list[FightView], scope: Scope) -> Outcome:
        g = self.gate("min_fights", scope)
        if len(views) < g:
            return self.silent(f"needs {g} fights, has {len(views)}")
        c = self._counts(views)
        ge = self.gate("min_expected", scope)
        if max(c["obs"], c["exp"]) < ge:
            return self.silent(f"needs {ge} downs, or more time in fights: you went down "
                               f"{c['obs']} times and the squad's rate predicts {c['exp']:.1f}")
        # Survival runs over all fights, and says so when one spec stands out on its own.
        standout = []
        for spec, sv in self.by_spec(views).items():
            cs = self._counts(sv)
            if len(sv) < len(views) and self._passes(sv, cs, scope) and self._fires(cs):
                standout.append((spec, sv, cs))
        if self._fires(c):
            ev = self._evidence(c, None)
            ev["spec_txt"] = "".join(
                f" On {spec} it was {cs['obs'] / cs['exp']:.1f}x ({cs['obs']} downs in "
                f"{len(sv)} fights, the squad's rate: {cs['exp']:.1f})."
                for spec, sv, cs in standout)
            return Outcome(advice=[self.advice(
                "me_deaths", "major", views, scope, impact=c["obs"] - c["exp"], evidence=ev,
                sample=f"{c['obs']} downs in {len(views)} fights, the squad's rate: "
                       f"{c['exp']:.1f}",
                examples=_recent_first(c["examples"]))])
        if standout:
            return Outcome(advice=[self.advice(
                "me_deaths", "major", sv, scope, impact=cs["obs"] - cs["exp"],
                evidence=self._evidence(cs, spec), spec=spec,
                sample=f"{cs['obs']} downs in {len(sv)} fights on {spec}, the squad's rate: "
                       f"{cs['exp']:.1f}",
                examples=_recent_first(cs["examples"])) for spec, sv, cs in standout])
        obs, exp = c["obs"], c["exp"]
        if obs * self.cfg["ratio"] <= exp and poisson_cdf(obs, exp) <= self.cfg["alpha"]:
            return Outcome(advice=[self.advice(
                "me_survivor", "positive", views, scope, impact=exp - obs,
                evidence=self._evidence(c, None),
                sample=f"{obs} downs in {len(views)} fights, the squad's rate: {exp:.1f}")])
        return Outcome()


class DownShare(Rule):
    """A share of the player's downs (with a cause) against the squad's share in the same
    fights: fires when well above it and unlikely at the squad's rate."""

    enabled_by_default = False  # fired at chance level in the calibration
    defaults = {"min_downs": 6, "margin": 0.15, "alpha": 0.05}
    what: str = ""  # "downs without stability" for the gate text

    def counts(self, d: dict[str, Any]) -> bool:
        return True

    def hit(self, d: dict[str, Any]) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def _counts(self, views: list[FightView]) -> dict[str, Any]:
        pool = [d for v in views for d in v.squad_downs if self.counts(d)]
        pooled = sum(1 for d in pool if self.hit(d)) / len(pool) if pool else 0.0
        c = {"n": 0, "k": 0, "exp": 0.0, "examples": [], "fights": 0}
        for v in views:
            mine = [d for d in v.downs if self.counts(d)]
            if not mine:
                continue
            others = [d for d in v.squad_downs if self.counts(d)]
            p = sum(1 for d in others if self.hit(d)) / len(others) if others else pooled
            hits = [d for d in mine if self.hit(d)]
            c["n"] += len(mine)
            c["k"] += len(hits)
            c["exp"] += len(mine) * p
            c["fights"] += 1
            c["examples"] += [_ex(v, d["t"]) for d in hits]
        return c

    def measure(self, views, scope, spec=None):
        c = self._counts(views)
        if c["n"] < self.gate("min_downs", scope):
            return None
        return (c["k"] - c["exp"]) / c["n"]

    def run(self, views: list[FightView], scope: Scope) -> Outcome:
        c = self._counts(views)
        g = self.gate("min_downs", scope)
        if c["n"] < g:
            return self.silent(f"needs {g} downs, has {c['n']}")
        n, k, exp = c["n"], c["k"], c["exp"]
        p = exp / n
        ev = {"hits": k, "downs": n, "share": pct(k / n), "squad_share": pct(p),
              "expected": round(exp, 1), **self.extra_evidence()}
        sample = f"{k} of {n} downs, the squad's share: {exp:.1f} of {n}"
        if k / n - p >= self.cfg["margin"] and binom_sf(k, n, p) <= self.cfg["alpha"]:
            return Outcome(advice=[self.advice(self.name, "major", views, scope,
                                               impact=k - exp, evidence=ev, sample=sample,
                                               examples=_recent_first(c["examples"]))])
        return Outcome()

    def extra_evidence(self) -> dict[str, Any]:
        return {}


class DownNoStab(DownShare):
    name = "me_down_no_stab"
    label = "Downs without stability"
    description = ("Your downs with no stability while most of your party had it, against the "
                   "squad's share of such downs in the same fights.")
    defaults = {**DownShare.defaults, "party_cover": 50}  # % of the party with stability

    def counts(self, d):
        return d["party_stab"] is not None

    def hit(self, d):
        return d["stab"] <= 0 and d["party_stab"] >= self.cfg["party_cover"]


class DownFar(DownShare):
    name = "me_down_far"
    label = "Downs far from the tag"
    description = ("Your downs far from the commander, against the squad's share in the same "
                   "fights (the same distance as the 'Caught out of position' note).")
    defaults = {**DownShare.defaults, "far_tag": 1000}  # inches, as out_of_position.far_tag

    def counts(self, d):
        return d["dist_tag"] is not None

    def hit(self, d):
        return d["dist_tag"] > self.cfg["far_tag"]

    def extra_evidence(self):
        return {"far_tag": self.cfg["far_tag"]}


class CaughtAlone(DownShare):
    name = "me_caught_alone"
    label = "Caught alone"
    description = ("Your downs with at most one other squad down within 4 s (picked off, not "
                   "bombed), against the squad's share in the same fights.")
    defaults = {**DownShare.defaults, "max_near": 1}

    def hit(self, d):
        return d["near"] <= self.cfg["max_near"]


class FirstDown(Rule):
    enabled_by_default = False  # fired at chance level in the calibration
    name = "me_first_down"
    label = "Among the first to go down"
    description = ("How often you were among the first players downed in fights with many "
                   "downs, against chance (first N / players downed).")
    defaults = {"min_squad_downs": 6, "first": 3, "min_fights": 5, "ratio": 1.5,
                "alpha": 0.05}

    def _counts(self, views: list[FightView]) -> dict[str, Any]:
        probs: list[float] = []
        hits, examples = 0, []
        for v in views:
            sq, rank = v.squad, v.first_rank
            if rank is None or sq["downs_total"] < self.cfg["min_squad_downs"]:
                continue
            probs.append(min(1.0, self.cfg["first"] / max(sq["players_downed"], 1)))
            if rank <= self.cfg["first"]:
                hits += 1
                examples.append(_ex(v, v.downs[0]["t"] if v.downs else None))
        return {"probs": probs, "hits": hits, "examples": examples}

    def measure(self, views, scope, spec=None):
        c = self._counts(views)
        if len(c["probs"]) < self.gate("min_fights", scope):
            return None
        return (c["hits"] - sum(c["probs"])) / len(c["probs"])

    def run(self, views: list[FightView], scope: Scope) -> Outcome:
        c = self._counts(views)
        n, g = len(c["probs"]), self.gate("min_fights", scope)
        if n < g:
            return self.silent(f"needs {g} fights with {self.cfg['min_squad_downs']}+ squad "
                               f"downs where you went down, has {n}")
        exp, k = sum(c["probs"]), c["hits"]
        ev = {"hits": k, "big_fights": n, "expected": round(exp, 1), "first": self.cfg["first"],
              "min_squad_downs": self.cfg["min_squad_downs"]}
        sample = f"{k} of {n} fights, chance: {exp:.1f}"
        if (k >= self.cfg["ratio"] * exp
                and poisson_binomial_sf(k, c["probs"]) <= self.cfg["alpha"]):
            return Outcome(advice=[self.advice(self.name, "major", views, scope, impact=k - exp,
                                               evidence=ev, sample=sample,
                                               examples=_recent_first(c["examples"]))])
        return Outcome()


# ---- play -----------------------------------------------------------------------------------


class FarFromTag(Rule):
    enabled_by_default = False  # fired for nobody in the calibration
    name = "me_far_from_tag"
    label = "Far from the tag"
    area = "play"
    description = ("Your typical distance to the commander in each fight against the squad "
                   "median; fires when you are much farther in most fights. Not for fights "
                   "you led.")
    defaults = {"factor": 1.5, "min_extra": 150, "min_share": 0.6, "min_fights": 5}

    def _fights(self, views: list[FightView]) -> list[tuple[FightView, float, float]]:
        out = []
        for v in views:
            if v.commander:
                continue
            you, _, _, sq = v.facts["peers"]["dist_tag"]
            if you is not None and sq:
                out.append((v, float(you), float(sq)))
        return out

    def _far(self, you: float, sq: float) -> bool:
        return you >= self.cfg["factor"] * sq and you - sq >= self.cfg["min_extra"]

    def measure(self, views, scope, spec=None):
        f = self._fights(views)
        if len(f) < self.gate("min_fights", scope):
            return None
        return sum(1 for _, y, s in f if self._far(y, s)) / len(f)

    def run(self, views: list[FightView], scope: Scope) -> Outcome:
        f = self._fights(views)
        g = self.gate("min_fights", scope)
        if len(f) < g:
            return self.silent(f"needs {g} fights with a commander (not led by you), "
                               f"has {len(f)}")
        far = [(v, y, s) for v, y, s in f if self._far(y, s)]
        share = len(far) / len(f)
        if share < self.cfg["min_share"]:
            return Outcome()
        ev = {"far_fights": len(far), "tag_fights": len(f), "share": pct(share),
              "you_dist": int(statistics.median(y for _, y, _ in f)),
              "squad_dist": int(statistics.median(s for _, _, s in f))}
        return Outcome(advice=[self.advice(
            self.name, "minor", views, scope, impact=1.0 + share, evidence=ev,
            sample=f"{len(far)} of {len(f)} fights",
            examples=_recent_first([_ex(v) for v, _, _ in far]))])


class PeerRule(Rule):
    """Compared per elite spec with players of the same spec and job in the same fight.

    The player's job on a spec is the one they had in most of their fights on it (fights
    without a job don't vote). In every fight on that spec they are compared with the other
    players of the spec who had that job there, also when their own output that fight
    pointed to another job: judging only the fights where it didn't would leave out exactly
    the fights where the job was done weakly.
    """

    area = "play"
    per_spec = True
    lower_is_better = False
    # Calibrated on the dev corpus (54 player+spec groups past the gate): 0.65 and 1.4 are
    # about the 13th and 88th percentile of the median ratio to peers.
    defaults = {"min_fights": 5, "min_peers": 2, "below": 0.65, "above": 1.4}
    positive: str = ""
    column = 1  # spec_peers: [count, job metric, cast, cancelled seconds]

    def _rows(self, views: list[FightView], spec: str) -> list[tuple[FightView, dict]]:
        out = []
        for v in views:
            r = v.spec_rows().get(spec)
            if r is not None and not v.commander and r["facts"].get("eligible"):
                out.append((v, r))
        return out

    @staticmethod
    def job(rows: list[tuple[FightView, dict]]) -> str | None:
        return majority([r["facts"].get("job") for _, r in rows
                         if r["facts"].get("job") is not None])

    def you(self, facts: dict[str, Any], job: str) -> float | None:  # pragma: no cover
        raise NotImplementedError

    def _ratios(self, rows: list[tuple[FightView, dict]], job: str
                ) -> list[tuple[FightView, float, dict]]:
        out = []
        for v, r in rows:
            ref = r["facts"].get("spec_peers", {}).get(job)
            you = self.you(r["facts"], job)
            if ref and ref[0] >= self.cfg["min_peers"] and ref[self.column] and you is not None:
                out.append((v, float(you) / float(ref[self.column]), r))
        return out

    def measure(self, views, scope, spec=None):
        if spec is None:
            return None
        rows = self._rows(views, spec)
        job = self.job(self._rows(views, spec))
        if job is None:
            return None
        ratios = self._ratios(rows, job)
        if len(ratios) < self.gate("min_fights", scope):
            return None
        return statistics.median(x for _, x, _ in ratios)

    def run(self, views: list[FightView], scope: Scope) -> Outcome:
        out = Outcome()
        for spec in sorted({s for v in views for s in v.specs}):
            res = self.run_spec(views, scope, spec)
            out.advice += res.advice
            out.gates += res.gates
        return out

    def run_spec(self, views: list[FightView], scope: Scope, spec: str) -> Outcome:
        rows = self._rows(views, spec)
        if not rows:
            return Outcome()
        job = self.job(rows)
        if job is None:
            return self.silent(f"no clear main job on {spec}", spec)
        ratios = self._ratios(rows, job)
        g = self.gate("min_fights", scope)
        if len(ratios) < g:
            return self.silent(f"needs {g} fights on {spec} with {self.cfg['min_peers']}+ other "
                               f"{spec}s on {JOB_TXT[job]}, has {len(ratios)}", spec)
        med = statistics.median(x for _, x, _ in ratios)
        ev = {"job_txt": JOB_TXT[job], "you_pct": pct(med), "peer_fights": len(ratios),
              "spec_fights": len(rows),
              "off_job": sum(1 for _, r in rows if r["facts"].get("job") != job),
              **self.evidence(ratios, job)}
        sample = self.sample(ev, spec, len(ratios))
        if med <= self.cfg["below"]:
            low = sorted(ratios, key=lambda x: x[1])
            return Outcome(advice=[self.advice(
                self.name, "minor", views, scope, impact=1.0 + 4 * (self.cfg["below"] - med),
                evidence=ev, sample=sample, spec=spec,
                examples=[_ex(v) for v, x, _ in low if x < 1])])
        if med >= self.cfg["above"]:
            return Outcome(advice=[self.advice(
                self.positive, "positive", views, scope,
                impact=1.0 + 2 * (med - self.cfg["above"]), evidence=ev, sample=sample,
                spec=spec)])
        return Outcome()

    def evidence(self, ratios: list[tuple[FightView, float, dict]], job: str) -> dict[str, Any]:
        return {}

    def sample(self, ev: dict[str, Any], spec: str, n: int) -> str:  # pragma: no cover
        raise NotImplementedError


class LowOutput(PeerRule):
    name = "me_low_output"
    label = "Low output for the role"
    positive = "me_top_output"
    description = ("Your main output on a spec (the job you had in most of your fights on it: "
                   "damage, strips, cleanses, healing or stability given) against players "
                   "with the same spec and job in the same fight. Positive when clearly above.")
    defaults = {**PeerRule.defaults}

    def you(self, facts, job):
        return facts["peers"][JOB_METRIC[job]][0]

    def sample(self, ev, spec, n):
        return f"median {ev['you_pct']}% of the other {spec}s on {ev['job_txt']}, {n} fights"


class LowActivity(PeerRule):
    name = "me_low_activity"
    label = "Few skills pressed"
    positive = "me_active"
    column = 2
    description = ("Your cast time without auto-attacks against players with the same spec and "
                   "job in the same fight, with the time lost to cancelled casts. Positive "
                   "when clearly above.")
    defaults = {**PeerRule.defaults, "below": 0.75, "above": 1.35}

    def you(self, facts, job):
        return facts["cast"]

    def evidence(self, ratios, job):
        refs = [r["facts"]["spec_peers"][job] for _, _, r in ratios]
        return {"you_cast": _med1([r["facts"]["cast"] for _, _, r in ratios], 0),
                "peer_cast": _med1([x[2] for x in refs], 0),
                "you_cancel": _med1([r["facts"]["peers"]["cancel_s"][0] for _, _, r in ratios]),
                "peer_cancel": _med1([x[3] for x in refs])}

    def sample(self, ev, spec, n):
        return (f"cast time {ev['you_cast']}% vs {ev['peer_cast']}% for the other {spec}s on "
                f"{ev['job_txt']}, {n} fights")


def _med1(values: list[Any], nd: int = 1) -> float:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return 0
    m = round(statistics.median(vals), nd)
    return int(m) if nd == 0 else m


class CcTaken(Rule):
    enabled_by_default = False  # fired for 1 of 76 players in the calibration
    name = "me_cc_taken"
    label = "CC'd more than the squad"
    area = "play"
    description = ("Crowd control you received per minute against the squad median in the same "
                   "fights, when your stability uptime was also below your party's. Not for "
                   "fights you led.")
    defaults = {"factor": 1.5, "min_fights": 5, "min_below_share": 0.5, "stab_gap": 10}
    lower_is_better = True

    def _fights(self, views):
        out = []
        for v in views:
            if v.commander:
                continue
            p = v.facts["peers"]
            you, _, _, sq = p["cc_taken"]
            if you is None or not sq:
                continue
            party = v.squad.get("party_stab_up")
            below = (party is not None and p["stab_up"][0] is not None
                     and p["stab_up"][0] < party - self.cfg["stab_gap"])
            out.append((v, float(you) / float(sq), below))
        return out

    def measure(self, views, scope, spec=None):
        f = self._fights(views)
        if len(f) < self.gate("min_fights", scope):
            return None
        return statistics.median(x for _, x, _ in f)

    def run(self, views, scope):
        f = self._fights(views)
        g = self.gate("min_fights", scope)
        if len(f) < g:
            return self.silent(f"needs {g} fights where the squad was CC'd, has {len(f)}")
        med = statistics.median(x for _, x, _ in f)
        below = sum(1 for *_, b in f if b)
        if med < self.cfg["factor"] or below / len(f) < self.cfg["min_below_share"]:
            return Outcome()
        ev = {"ratio": round(med, 1), "cc_fights": len(f), "below_fights": below}
        return Outcome(advice=[self.advice(
            self.name, "minor", views, scope, impact=1.0 + min(med - self.cfg["factor"], 1.0),
            evidence=ev, sample=f"{med:.1f}x the squad median, {len(f)} fights",
            examples=_recent_first([_ex(v) for v, x, b in f if b and x >= self.cfg["factor"]]))])


class NoFood(Rule):
    name = "me_no_food"
    label = "Food and utility"
    area = "play"
    description = "Fights without food or without a utility (sharpening stone, oil, ...)."
    defaults = {"min_fights": 5, "max_missing": 0.25}

    def _counts(self, views):
        known = [v for v in views if v.flag("food") is not None]
        food = [v for v in known if v.flag("food") is False]
        util = [v for v in known if v.flag("utility") is False]
        either = [v for v in known if v.flag("food") is False or v.flag("utility") is False]
        return known, food, util, either

    def measure(self, views, scope, spec=None):
        known, _, _, either = self._counts(views)
        if len(known) < self.gate("min_fights", scope):
            return None
        return len(either) / len(known)

    def run(self, views, scope):
        known, food, util, either = self._counts(views)
        g = self.gate("min_fights", scope)
        if len(known) < g:
            return self.silent(f"needs {g} fights whose log lists consumables, has {len(known)}")
        share = len(either) / len(known)
        if share < self.cfg["max_missing"]:
            return Outcome()
        ev = {"no_food": len(food), "no_utility": len(util), "known": len(known),
              "missing": len(either), "share": pct(share)}
        return Outcome(advice=[self.advice(
            self.name, "minor", views, scope, impact=0.5, evidence=ev,
            sample=f"{len(either)} of {len(known)} fights",
            examples=_recent_first([_ex(v) for v in either]))])


CAUSE_RULES: list[str] = ["me_down_no_stab", "me_down_far", "me_caught_alone", "me_first_down"]
