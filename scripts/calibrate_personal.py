"""Calibrate the personal rules ("My play") against every player in your logs.

Analyzes parsed Elite Insights JSON (data/dev_corpus by default), builds each account's fights
as the review does, and prints:
  1. per rule: how many players (per spec for output and activity) pass its gate, and for how
     many of those it fires (an issue) or gives a strength. A useful rule fires for a minority;
  2. how often a player's job flips between fights on one spec;
  3. the recording player's profile (the account that recorded the most fights) and their
     review per day, as the page would show it.

Player and account names are only printed to the terminal; don't paste them into docs.

Usage:  uv run python scripts/calibrate_personal.py [--mode zerg|gvg] [--examples RULE]
                                                    [--account NAME] [folder ...]
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from wvw_analyzer import paths
from wvw_analyzer.analysis import Skipped, analyze_file
from wvw_analyzer.coach.data import build_views, majority
from wvw_analyzer.coach.registry import RULES
from wvw_analyzer.coach.review import run_rules
from wvw_analyzer.config import Settings


def _one(args: tuple[str, str]) -> dict[str, Any] | None:
    path, mode = args
    try:
        a = analyze_file(Path(path), Settings(), mode)
    except Skipped:
        return None
    s = a.summary
    return {"name": Path(path).name, "start": s["start"], "dur_s": s["durationS"],
            "mode": s["mode"], "result": s["result"], "map": s["map"], "facts": a.facts}


def load(files: list[Path], mode: str) -> tuple[dict[int, dict], dict[str, list[dict]]]:
    fights: dict[int, dict] = {}
    rows: dict[str, list[dict]] = defaultdict(list)
    with ProcessPoolExecutor(8) as ex:
        results = list(ex.map(_one, [(str(f), mode) for f in files]))
    for fid, res in enumerate(r for r in results if r):
        day = (res["start"] or "")[:10]
        fights[fid] = {**{k: res[k] for k in ("name", "start", "dur_s", "mode", "result",
                                               "map")}, "session_id": day}
        for r in res["facts"]:
            rows[r["account"]].append({**r, "fight_id": fid})
    return fights, rows


def fire_rates(per_account: dict[str, dict], n_accounts: int) -> None:
    print(f"\n== Fire rates over {n_accounts} accounts (profile scope, all their fights) ==")
    print(f"{'rule':<18} {'units':>6} {'gated':>6} {'passed':>6} {'issue':>6} {'%':>5} "
          f"{'strength':>8} {'%':>5}")
    for cls in RULES:
        units = passed = issue = keep = gated = 0
        for review in per_account.values():
            names = {cls.name}
            adv = [a for b in ("work", "more", "keep") for a in review[b]
                   if a["detector"] in names]
            gate = [g for g in review["gates"] if g["rule"] == cls.name]
            if cls.per_spec:
                specs = review["_specs"]
                u = len(specs)
                gated_specs = {g["spec"] for g in gate}
                units += u
                gated += len(gated_specs)
                passed += u - len(gated_specs)
            else:
                units += 1
                gated += bool(gate)
                passed += not gate
            issue += sum(1 for a in adv if a["severity"] != "positive")
            keep += sum(1 for a in adv if a["severity"] == "positive")
        print(f"{cls.name:<18} {units:>6} {gated:>6} {passed:>6} {issue:>6} "
              f"{_rate(issue, passed)} {keep:>8} {_rate(keep, passed)}")


def _rate(x: int, n: int) -> str:
    return f"{100 * x / n:4.0f}%" if n else "    -"


def job_flips(rows: dict[str, list[dict]]) -> None:
    flips, groups = [], 0
    for acc_rows in rows.values():
        by_spec: dict[str, list[str | None]] = defaultdict(list)
        for r in acc_rows:
            f = r["facts"]
            if r["in_fight"] and f.get("eligible") and not r["is_commander"]:
                by_spec[r["profession"]].append(f.get("job"))
        for jobs in by_spec.values():
            if len(jobs) < 3:
                continue
            groups += 1
            maj = majority([j for j in jobs if j is not None])  # as PeerRule.job
            flips.append(sum(1 for j in jobs if j != maj) / len(jobs) if maj else 1.0)
    if not flips:
        return
    print(f"\n== Job per spec: {groups} account+spec groups with 3+ fights ==")
    unstable = sum(1 for x in flips if x >= 1 / 3)
    print(f"median share of fights off the main job: {statistics.median(flips):.0%}; "
          f"groups with no clear main job or a third or more off it: "
          f"{unstable} ({unstable / len(flips):.0%})")


def show(review: dict[str, Any], fights: dict[int, dict], examples: bool = True) -> None:
    def line(a: dict[str, Any]) -> None:
        spec = f" [{a['spec']}]" if a.get("spec") else ""
        trend = f" trend: {a['trend']}" if a.get("trend") else ""
        print(f"  - {a['title']}{spec}  ({a['sample']}; impact {a['impact']}){trend}")
        print(f"    {a['cause']}")
        if examples and a.get("examples"):
            ex = ", ".join(f"{fights[e['fightId']]['name'][:15]}"
                           + (f"@{e['t']:.0f}s" if e.get("t") is not None else "")
                           for e in a["examples"][:4])
            print(f"    examples: {ex}")

    if review["nothing"]:
        print(f"  {review['nothing']['title']}")
    for title, key in (("Work on", "work"), ("More", "more"), ("Keep doing", "keep")):
        if review[key]:
            print(f" {title}:")
            for a in review[key]:
                line(a)
    if review["gates"]:
        print(" Silent (gate):")
        for g in review["gates"]:
            spec = f" [{g['spec']}]" if g.get("spec") else ""
            print(f"  - {g['rule']}{spec}: {g['need']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="*")
    ap.add_argument("--mode", default="zerg", choices=["zerg", "gvg"])
    ap.add_argument("--examples", help="list every account's example fights for this rule")
    ap.add_argument("--account", help="show this account's profile instead of the recorder's")
    args = ap.parse_args()
    folders = [Path(p) for p in args.folders] or [paths.data_dir() / "dev_corpus"]
    files = sorted({f for d in folders if d.exists() for f in d.glob("*.json*")})
    if not files:
        print("No EI JSON found.")
        return 1
    # The default thresholds are what is being calibrated, with every rule on (some are off
    # by default); the profiles below show what the page shows (the defaults).
    overrides: dict = {cls.name: {"enabled": True} for cls in RULES}
    defaults: dict = {}
    fights, rows = load(files, args.mode)
    n_rows = sum(len(v) for v in rows.values())
    in_fight = sum(1 for v in rows.values() for r in v if r["in_fight"])
    print(f"{len(fights)} analyzed fights, {len(rows)} accounts, {n_rows} rows "
          f"({in_fight} in the fight)")

    per_account: dict[str, dict] = {}
    for acc, acc_rows in rows.items():
        views = build_views(acc_rows, fights)
        if not views:
            continue
        review = run_rules(views, "profile", overrides)
        review["_specs"] = sorted({s for v in views if not v.commander for s in v.specs
                                   if v.spec_rows()[s]["facts"].get("eligible")})
        review["_fights"] = len(views)
        per_account[acc] = review
    sizes = [r["_fights"] for r in per_account.values()]
    print(f"fights per account: median {statistics.median(sizes)}, "
          f"10+ fights: {sum(1 for s in sizes if s >= 10)}, "
          f"30+ fights: {sum(1 for s in sizes if s >= 30)}")
    fire_rates(per_account, len(per_account))
    job_flips(rows)
    nothing = sum(1 for r in per_account.values() if r["nothing"])
    print(f"\n'Nothing stands out': {nothing} of {len(per_account)} accounts")

    if args.examples:
        print(f"\n== Examples for {args.examples} ==")
        for acc, review in per_account.items():
            for a in review["work"] + review["more"] + review["keep"]:
                if a["detector"] == args.examples:
                    print(f"{acc} ({review['_fights']} fights): {a['sample']}")
                    for e in a["examples"]:
                        t = f" at {e['t']:.0f}s" if e.get("t") is not None else ""
                        print(f"   {fights[e['fightId']]['name']}{t}")

    recorder = args.account or Counter(
        r["account"] for v in rows.values() for r in v if r["is_pov"]).most_common(1)[0][0]
    views = build_views(rows[recorder], fights)
    print(f"\n== Profile of {'the recording player' if not args.account else recorder} "
          f"({len(views)} fights) ==")
    show(run_rules(views, "profile", defaults), fights)
    by_day: dict[str, list] = defaultdict(list)
    for v in views:
        by_day[v.session_id].append(v)
    for day, vs in sorted(by_day.items()):
        print(f"\n-- Session {day} ({len(vs)} fights) --")
        show(run_rules(vs, "session", defaults), fights, examples=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
