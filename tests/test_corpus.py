"""Integration check over real Elite Insights JSON, if a local corpus exists.

Put EI JSON (.json.gz) files in data/dev_corpus (git-ignored) to enable it.
"""

from collections import Counter
from pathlib import Path

import pytest

from wvw_analyzer.analysis import Skipped, analyze_file
from wvw_analyzer.config import Settings

CORPUS = Path(__file__).resolve().parents[1] / "data" / "dev_corpus"
FILES = sorted(CORPUS.glob("*.json.gz")) if CORPUS.exists() else []


@pytest.mark.skipif(not FILES, reason="no local EI corpus in data/dev_corpus")
def test_corpus_analyzes_without_errors():
    results = Counter()
    for f in FILES:
        try:
            a = analyze_file(f, Settings())
        except Skipped:
            results["skipped"] += 1
            continue
        results[a.summary["result"]] += 1
        for fnd in a.notes["issues"] + a.notes["positives"]:
            assert "{" not in fnd["cause"], fnd
    assert results["win"] + results["loss"] + results["even"] > 0
