"""Calibrate detector thresholds against your own fights.

Runs the analyzer over parsed Elite Insights JSON (the app's cache by default) and prints:
  1. how often each detector fires in won vs lost fights (good detectors fire mostly in losses),
  2. medians of the key metrics per outcome, to pick thresholds that separate wins from losses.

Usage:  uv run python scripts/calibrate.py [folder-with-json.gz ...]
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from wvw_analyzer import paths
from wvw_analyzer.analysis import Skipped, notes_for, skip_reason
from wvw_analyzer.config import ConfigStore
from wvw_analyzer.detectors.util import window_mean
from wvw_analyzer.ingest.loader import is_wvw, load_fight, read_ei_json
from wvw_analyzer.metrics.summary import compute_metrics


def metrics_row(m) -> dict:
    s, tl = m.summary, m.timeline
    e0, e1 = tl.engage_start, tl.engage_end
    downs = tl.squad_downs
    cleave = sum(r["against_downed"] for r in m.players)
    condi = sum(r["condi_taken"] for r in m.players)
    return {
        "result": s["result"],
        "enemy_ratio": s["outnumberRatio"],
        "stab_cov": window_mean(tl.squad.get("stab"), e0, e1),
        "resist_cov": window_mean(tl.squad.get("resist"), e0, e1),
        "avg_boons": window_mean(tl.squad.get("boons"), e0, e1),
        "avg_conditions": window_mean(tl.squad.get("conditions"), e0, e1),
        "condi_share": condi / s["squadDamageTaken"] if s["squadDamageTaken"] else np.nan,
        "boons_lost_per_strip": s["squadBoonsLost"] / max(s["squadStrips"], 1),
        "enemy_conversion": s["enemyDeaths"] / s["enemyDowns"] if s["enemyDowns"] else np.nan,
        "own_death_rate": s["squadDeaths"] / s["squadDowns"] if s["squadDowns"] else np.nan,
        "downs_nostab_share": (sum(1 for d in downs if d["stab"] <= 0) / len(downs)
                               if downs else np.nan),
        "downs_far_share": (sum(1 for d in downs if (d["dist_tag"] or 0) > 1000) / len(downs)
                            if downs else np.nan),
        "cleave_share": cleave / s["squadDamage"] if s["squadDamage"] else np.nan,
    }


def main() -> int:
    folders = [Path(p) for p in sys.argv[1:]] or [paths.data_dir() / "ei",
                                                  paths.data_dir() / "dev_corpus"]
    files = sorted({f for d in folders if d.exists() for f in d.glob("*.json*")})
    if not files:
        print("No EI JSON found. Import some logs in the app first.")
        return 1
    settings = ConfigStore().settings
    fires: dict[str, Counter] = defaultdict(Counter)
    results: Counter = Counter()
    rows = []
    for f in files:
        try:
            d = read_ei_json(f)
            if not is_wvw(d):
                continue
            fight = load_fight(d, f.name)
            if skip_reason(fight, settings.filters):
                continue
            m = compute_metrics(fight)
        except (Skipped, ValueError, KeyError, OSError) as e:
            print(f"skip {f.name}: {e}")
            continue
        res = m.summary["result"]
        results[res] += 1
        rows.append(metrics_row(m))
        notes = notes_for(m, settings)
        keys = {x["key"] for k in ("issues", "more", "positives") for x in notes[k]}
        for k in keys:
            fires[k][res] += 1

    print(f"\n{sum(results.values())} fights: {dict(results)}\n")
    print("Detector fire rate by outcome (lift = loss rate / win rate):")
    table = []
    for key, c in fires.items():
        wr = c["win"] / max(results["win"], 1)
        lr = c["loss"] / max(results["loss"], 1)
        table.append((key, round(100 * wr), round(100 * lr), round(lr / wr, 1) if wr else np.inf))
    df = pd.DataFrame(table, columns=["finding", "% of wins", "% of losses", "lift"])
    print(df.sort_values("lift", ascending=False).to_string(index=False))

    print("\nMetric medians by outcome:")
    mdf = pd.DataFrame(rows)
    print(mdf.groupby("result").median(numeric_only=True).T.round(2).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
