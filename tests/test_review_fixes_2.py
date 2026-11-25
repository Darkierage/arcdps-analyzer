"""Regression tests for the whole-app review after 0.5.0 (analysis inputs, GvG lulls, debriefs,
second instance, config safety, settings validation, LLM shutdown)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from factory import zerg
from wvw_analyzer import main
from wvw_analyzer.analysis import analyze_ei
from wvw_analyzer.api.app import create_app
from wvw_analyzer.config import ConfigStore, Settings
from wvw_analyzer.detectors import registry
from wvw_analyzer.llm.manager import LlmService
from wvw_analyzer.metrics.aggregate import aggregate_session
from wvw_analyzer.metrics.rounds import Round, round_of
from wvw_analyzer.state import AppState
from wvw_analyzer.store.db import Database


# ---- analysis ---------------------------------------------------------------------------
def test_events_in_the_lull_belong_to_no_round():
    rounds = [Round(1.0, 30.0, 33.0), Round(71.0, 100.0, 103.0)]
    assert round_of(10, rounds) == 0
    assert round_of(32, rounds) == 0  # within the call-off grace
    assert round_of(45, rounds) is None  # after round 1's call-off, before round 2
    assert round_of(70.5, rounds) == 1  # activity is counted in whole seconds
    assert round_of(80, rounds) == 1
    assert round_of(110, rounds) is None
    assert round_of(0.2, rounds) == 0  # before the first round: still round 1


def test_session_totals_leave_out_kills_after_a_calloff():
    gvg = {"summary": {"mode": "gvg", "result": "win", "squadDeaths": 3, "squadDeathsLate": 1,
                       "enemyDeaths": 5, "enemyDeathsLate": 2, "squadDowns": 4,
                       "enemyDowns": 6, "enemyDownsLate": 1, "rounds": []},
           "notes": {}, "players": [], "id": 1}
    zerg_fight = {"summary": {"mode": "zerg", "result": "loss", "squadDeaths": 2,
                              "enemyDeaths": 1, "squadDowns": 2, "enemyDowns": 1},
                  "notes": {}, "players": [], "id": 2}
    agg = aggregate_session([gvg, zerg_fight])
    t = agg["totals"]
    assert (t["squadDeaths"], t["enemyDeaths"], t["enemyDowns"]) == (2 + 2, 3 + 1, 5 + 1)
    assert agg["fights"][0]["enemyDeaths"] == 3 and agg["fights"][1]["squadDeaths"] == 2


def test_squad_totals_count_only_players_in_the_fight():
    a = analyze_ei(zerg(10, downs_at=[30, 30.5]), "x", Settings())
    in_fight = [r for r in a.stats["players"] if r.get("in_fight", True)]
    assert a.summary["squadDowns"] == sum(r["downs"] for r in in_fight)
    assert a.summary["squadDeaths"] == sum(r["deaths"] for r in in_fight)


def test_no_healing_is_only_judged_where_healing_was_recorded():
    from wvw_analyzer.detectors.player_outliers import _known

    rows = [{"has_heal_data": True, "healing": 0}, {"has_heal_data": False, "healing": 0}]
    assert _known(rows, "healing") == rows[:1] and _known(rows, "damage") == rows


# ---- stale debrief ------------------------------------------------------------------------
def test_reanalysis_keeps_the_debrief_only_if_nothing_changed(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    fid = db.add_fight("/x/a.zevtc", None, 0)
    a = analyze_ei(zerg(10), "a", Settings())
    db.save_analysis(fid, a.summary, a.stats, a.notes)
    db.save_debrief(fid, "Result: win\n- old")
    db.save_analysis(fid, a.summary, a.stats, a.notes)  # same output: still valid
    assert db.analysis(fid)["debrief"]
    b = analyze_ei(zerg(10, downs_at=[30, 30.5, 31, 31.5]), "a", Settings())
    db.save_analysis(fid, b.summary, b.stats, b.notes)  # new notes: the old wording goes
    assert db.analysis(fid)["debrief"] is None


def test_a_version_bump_alone_keeps_the_debrief(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    fid = db.add_fight("/x/a.zevtc", None, 0)
    a = analyze_ei(zerg(10), "a", Settings())
    db.save_analysis(fid, a.summary, a.stats, a.notes)
    db.save_debrief(fid, "Result: win\n- old")
    bumped = {**a.summary, "analyzerVersion": a.summary["analyzerVersion"] + 1}
    db.save_analysis(fid, bumped, a.stats, a.notes)  # same notes and facts: still valid
    assert db.analysis(fid)["debrief"]
    db.save_analysis(fid, {**bumped, "topIssue": "Something else"}, a.stats, a.notes)
    assert db.analysis(fid)["debrief"] is None


# ---- second instance ------------------------------------------------------------------------
def test_second_launch_finds_an_instance_on_a_later_port(monkeypatch):
    busy = {8765: "other", 8766: "ours"}
    monkeypatch.setattr(main, "_port_free", lambda host, port: port not in busy)
    monkeypatch.setattr(main, "_is_our_app", lambda host, port: busy.get(port) == "ours")
    assert main.choose_port("127.0.0.1", 8765) == (8766, True)
    busy[8766] = "other"
    assert main.choose_port("127.0.0.1", 8765) == (8767, False)


# ---- config safety --------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["{not: yaml: [", "- a list\n", "port: [1, 2]\n"])
def test_damaged_config_starts_with_defaults_and_keeps_a_copy(tmp_path: Path, text: str):
    path = tmp_path / "config.yaml"
    path.write_text(text)
    store = ConfigStore(path)
    assert store.settings.port == 8765
    if text == "port: [1, 2]\n":  # one bad value: only that value is reset
        assert store.settings.onboarded and not list(tmp_path.glob("config.yaml.broken-*"))
    else:
        assert not store.settings.onboarded  # setup screen again
        assert list(tmp_path.glob("config.yaml.broken-*"))[0].read_text() == text


def test_out_of_range_values_fall_back_to_defaults(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("log_dir: /x\nrecording:\n  poll_interval_s: 0\n"
                    "gvg:\n  round_gap_s: 10\n  calloff_grace_s: 20\n")
    s = ConfigStore(path).settings
    assert s.log_dir == "/x" and s.recording.poll_interval_s == 2.0
    assert (s.gvg.round_gap_s, s.gvg.calloff_grace_s) == (25, 3)


def test_config_is_written_atomically(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.yaml")
    store.update({"llm": {"threads": 3}})
    assert not list(tmp_path.glob("*.tmp"))
    assert ConfigStore(tmp_path / "config.yaml").settings.llm.threads == 3


# ---- settings validation (API) ----------------------------------------------------------------
def test_settings_api_rejects_unsafe_and_invalid_values(tmp_path: Path):
    state = AppState(ConfigStore(tmp_path / "config.yaml"), Database(tmp_path / "t.db"))
    with TestClient(create_app(state)) as client:
        def put(patch):
            return client.put("/api/settings", json=patch)

        assert put({"host": "0.0.0.0"}).status_code == 400
        assert put({"port": 9000}).status_code == 400
        assert put({"host": "127.0.0.1", "port": 8765}).status_code == 200  # unchanged: fine
        assert put({"recording": {"poll_interval_s": 0}}).status_code == 400
        assert put({"gvg": {"round_gap_s": 10, "calloff_grace_s": 12}}).status_code == 400
        assert put({"detectors": {"early_cascade": {"min_downs": 0}}}).status_code == 400
        assert put({"detectors": {"early_cascade": {"min_downs": "abc"}}}).status_code == 400
        assert put({"detectors": {"early_cascade": {"enabled": "false"}}}).status_code == 400
        assert put({"detectors": {"nope": {}}}).status_code == 400
        ok = put({"detectors": {"early_cascade": {"enabled": False, "min_downs": 5.0}}})
        assert ok.status_code == 200
        assert state.config.settings.detectors == {
            "early_cascade": {"enabled": False, "min_downs": 5}}


def test_detector_override_check_keeps_valid_values():
    assert registry.check_overrides({"comp_audit": {"low_cleanse_share": 0}}) == {
        "comp_audit": {"low_cleanse_share": 0}}  # a share may be 0 (turns that check off)


# ---- LLM shutdown -----------------------------------------------------------------------------
def test_llm_is_never_started_again_after_the_final_shutdown(tmp_path: Path):
    llm = LlmService(ConfigStore(tmp_path / "config.yaml"), None)  # type: ignore[arg-type]
    llm.shutdown(final=True)
    with pytest.raises(RuntimeError, match="closing"):
        llm._start()
