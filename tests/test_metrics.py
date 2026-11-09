import json
from datetime import date

import pytest

from kpi_lab.metrics import summarize
from kpi_lab.store import connect, read_snapshot

from .conftest import AS_OF


def test_hand_calculated_delivery_metrics(lab):
    _, db, *_ = lab
    with connect(db) as connection:
        first, second = summarize(*read_snapshot(connection, AS_OF), AS_OF)
    assert (first.name, second.name) == ("D1", "D2")
    assert first.first_seen == date(2025, 3, 9)
    assert second.first_seen == date(2025, 3, 16)
    kpis = first.kpis
    assert (kpis.planned, kpis.executed, kpis.passed, kpis.failed, kpis.blocked) == (4, 3, 2, 1, 1)
    assert kpis.progress_pct == 75
    assert kpis.pass_rate_pct == pytest.approx(66.66666667)
    assert kpis.flaky == 2
    assert kpis.open_by_severity == {
        "blocker": 1, "critical": 1, "major": 0, "minor": 1, "trivial": 0,
    }
    assert kpis.average_open_age_days == pytest.approx((7 + 15 + 0) / 3)
    assert kpis.oldest_open_age_days == 15
    assert [(risk.key, risk.age_days) for risk in kpis.risks] == [
        ("LAB-1", 7), ("LAB-2", 15), ("LAB-4", 0),
    ]
    assert [(week.starts.isoformat(), week.new, week.closed) for week in kpis.weeks] == [
        ("2025-02-24", 1, 0), ("2025-03-03", 1, 0),
        ("2025-03-10", 1, 1), ("2025-03-17", 1, 0),
    ]
    assert (second.kpis.progress_pct, second.kpis.pass_rate_pct, second.kpis.flaky) == (100, 100, 0)
    assert second.kpis.open_by_severity["major"] == second.kpis.open_by_severity["trivial"] == 1


def test_hand_calculated_component_metrics(lab):
    _, db, *_ = lab
    with connect(db) as connection:
        first, _ = summarize(*read_snapshot(connection, AS_OF), AS_OF)
    orders = first.components["Orders"]
    assert (orders.planned, orders.executed, orders.passed, orders.failed, orders.blocked) == (
        3, 2, 1, 1, 1,
    )
    assert (orders.progress_pct, orders.pass_rate_pct, orders.flaky) == (100 * 2 / 3, 50, 2)
    assert orders.open_by_severity["blocker"] == 1
    assert orders.average_open_age_days == orders.oldest_open_age_days == 7
    assert [(week.starts.isoformat(), week.new, week.closed) for week in orders.weeks] == [
        ("2025-03-03", 1, 0), ("2025-03-10", 1, 1),
    ]
    payments = first.components["Payments"]
    assert payments.pass_rate_pct == 100
    assert payments.open_by_severity["critical"] == 1
    support = first.components["Support"]
    assert support.planned == support.executed == 0
    assert support.progress_pct is support.pass_rate_pct is None


def test_as_of_trend_and_empty_history(lab, capsys):
    call, _, *_ = lab
    capsys.readouterr()
    assert call("kpis", "--as-of", "2025-03-18") == 0
    values = json.loads(capsys.readouterr().out)
    assert [item["name"] for item in values] == ["D1", "D2"]
    assert values[1]["kpis"]["pass_rate_pct"] == 0
    assert values[1]["kpis"]["flaky"] == 1
    assert values[0]["kpis"]["open_by_severity"]["minor"] == 0
    assert values[0]["kpis"]["weeks"][-1] == {"starts": "2025-03-17", "new": 1, "closed": 1}
    assert call("kpis", "--as-of", "2025-02-01") == 0
    assert json.loads(capsys.readouterr().out) == []
