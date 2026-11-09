import json
from dataclasses import replace
from datetime import date

import pytest

from kpi_lab.metrics import KPIs, Risk
from kpi_lab.readiness import failed_gates, load_gates, load_milestones

from .conftest import AS_OF, GATES, run_file

BASELINE = KPIs(100, 95, 94, 1, 5, 95, 98, 0, {}, None, None, [], [])


@pytest.mark.parametrize(("field", "passing", "failing", "message"), [
    ("progress_pct", 95, 94.99, "Test progress"),
    ("pass_rate_pct", 98, 97.99, "Pass rate"),
    ("risks", [], [Risk("B-1", "blocked", "blocker", AS_OF, 0, "API", "D1")], "open blocker"),
    ("risks", [Risk("C-1", "old", "critical", date(2025, 3, 3), 14, "API", "D1")],
     [Risk("C-1", "old", "critical", date(2025, 3, 2), 15, "API", "D1")], "C-1 (15 days)"),
])
def test_gate_boundaries(field, passing, failing, message):
    gates = load_gates(GATES)
    assert not failed_gates(replace(BASELINE, **{field: passing}), gates)
    failures = failed_gates(replace(BASELINE, **{field: failing}), gates)
    assert len(failures) == 1
    assert message in failures[0]


def test_no_tests_means_no_go():
    gates = load_gates(GATES)
    failures = failed_gates(replace(BASELINE, progress_pct=None, pass_rate_pct=None), gates)
    assert failures == ["Test progress unavailable (requires at least 95%)",
                        "Pass rate unavailable (requires at least 98%)"]


def test_readiness_shows_all_failures_risks_and_milestones(lab, capsys):
    call, _, _, _, milestones, _ = lab
    capsys.readouterr()
    assert call("readiness", "--gates", GATES, "--milestones", milestones, "--as-of", AS_OF) == 0
    first, second, planned = json.loads(capsys.readouterr().out)
    assert [first["decision"], second["decision"], planned["decision"]] == ["NO GO", "GO", "NO GO"]
    assert len(first["reasons"]) == 4
    assert "LAB-1" in first["reasons"][2]
    assert "LAB-2 (15 days)" in first["reasons"][3]
    assert [risk["key"] for risk in first["risks"]] == ["LAB-1", "LAB-2", "LAB-4"]
    assert first["milestones"][0] == {"name": "Integration cutoff", "day": "2025-03-19"}
    assert planned["delivery"] == "D3"


@pytest.mark.parametrize(("content", "message"), [
    ("[1, 2]", "expected a YAML mapping"),
    ("x: [", "expected"),
    ("min_progress_pct: 95", "expected gate keys"),
])
def test_bad_gate_config(tmp_path, content, message):
    with pytest.raises(ValueError, match=message):
        load_gates(run_file(tmp_path, "gates.yml", content))


@pytest.mark.parametrize(("key", "replacement", "message"), [
    ("min_progress_pct: 95", "min_progress_pct: 101", "percentage"),
    ("max_open_blockers: 0", "max_open_blockers: true", "nonnegative integer"),
])
def test_rejects_bad_gate_limits(tmp_path, key, replacement, message):
    body = GATES.read_text(encoding="utf-8").replace(key, replacement)
    with pytest.raises(ValueError, match=message):
        load_gates(run_file(tmp_path, "gates.yml", body))


@pytest.mark.parametrize(("content", "message"), [
    ("D1: [review]", "milestone mappings"),
    ("D1: {4: 2025-03-03}", "invalid milestone name"),
    ("D1: {Review: next month}", "invalid date"),
])
def test_bad_milestones(tmp_path, content, message):
    with pytest.raises(ValueError, match=message):
        load_milestones(run_file(tmp_path, "milestones.yml", content))
