import sqlite3

import pytest

from kpi_lab.importers import read_issues, read_junit, read_junit_tree
from kpi_lab.store import connect, read_snapshot, save_import

from .conftest import AS_OF, ISSUES, run_file


@pytest.mark.parametrize(("name", "body", "error"), [
    ("D1/unit/Orders/2025-03-09T090000Z.xml", "<testsuite>", "no element found"),
    ("D1/unit/Orders/2025-03-09T090000Z.xml", "<notjunit/>", "expected a testsuite"),
    ("D1/unit/Orders/2025-03-09T090000Z.xml", "<testsuite/>", "no testcases"),
    ("D1/unit/Orders/2025-03-09T090000Z.xml",
     '<testsuite><testcase name="a"/><testcase name="a"/></testsuite>', "duplicate"),
    ("D1/unit/Orders/2025-03-09T090000Z.xml",
     '<!DOCTYPE x [<!ENTITY x "value">]><testsuite/>', "DTDForbidden"),
    ("D1/acceptance/Orders/2025-03-09T090000Z.xml", "<testsuite/>", "test level"),
    ("D1/unit/Orders/bad.xml", "<testsuite/>", "does not match format"),
    ("D1/unit/Orders/2025-3-09T090000Z.xml", "<testsuite/>", "run filename"),
    ("Orders/bad.xml", "<testsuite/>", "not enough values"),
])
def test_bad_junit(tmp_path, name, body, error):
    with pytest.raises(ValueError, match=error):
        read_junit(run_file(tmp_path, name, body), tmp_path)


def test_junit_tree_and_outcomes(lab, tmp_path):
    _, _, root, _, _, _ = lab
    runs = read_junit_tree(root)
    assert len(runs) == 5
    assert runs[1].component == "Orders"
    assert runs[1].timestamp.isoformat() == "2025-03-09T09:00:00+00:00"
    assert [case.outcome for case in runs[1].results] == ["passed", "failed", "blocked"]
    assert [case.outcome for case in runs[2].results] == ["passed", "failed"]
    with pytest.raises(ValueError, match="no JUnit XML"):
        read_junit_tree(tmp_path / "missing")


@pytest.mark.parametrize(("transform", "error"), [
    (lambda csv: csv.replace("summary", "text", 1), "headers"),
    (lambda csv: csv.replace("summary", "key", 1), "headers"),
    (lambda csv: csv.replace("=1+1", "", 1), "blank"),
    (lambda csv: csv.replace("blocker", "urgent", 1), "unknown severity"),
    (lambda csv: csv.replace("In Progress", "Done", 1), "must agree"),
    (lambda csv: csv.replace("2025-03-11", "2025-03-01", 1), "precedes"),
    (lambda csv: csv.replace("2025-03-11", "tomorrow", 1), "Invalid isoformat"),
    (lambda csv: csv.replace("LAB-2", "LAB-1", 1), "duplicate issue"),
    (lambda csv: csv.replace("Orders,D1", "Orders,D1,extra", 1), "number of fields"),
    (lambda csv: csv.replace("Orders,D1", "Orders", 1), "number of fields"),
    (lambda csv: csv.replace("=1+1", '"unterminated', 1), "unexpected end"),
])
def test_bad_csv(tmp_path, transform, error):
    with pytest.raises(ValueError, match=error):
        read_issues(run_file(tmp_path, "issues.csv", transform(ISSUES)))


def test_csv_accepts_bom_and_quoted_summary(tmp_path):
    path = run_file(tmp_path, "issues.csv",
                    "\ufeff" + ISSUES.replace("=1+1", '"callback, retry"'))
    issues = read_issues(path)
    assert issues[0].summary == "callback, retry"
    assert issues[0].status == "in progress"
    assert issues[2].resolved.isoformat() == "2025-03-11"


def test_reimport_is_idempotent_and_corrects_existing_data(lab):
    call, db, root, issues, _, first = lab
    assert call("import", "--junit-dir", root, "--issues", issues) == 0
    with connect(db) as connection:
        tests, tickets = read_snapshot(connection, AS_OF)
        assert len(tests) == 7
        assert len(tickets) == 6
    first.write_text('<testsuite><testcase classname="order" name="valid"/></testsuite>',
                     encoding="utf-8")
    issues.write_text(ISSUES.replace("In Progress,2025-03-10,,", "Done,2025-03-10,2025-03-13,"),
                      encoding="utf-8")
    assert call("import", "--junit-dir", root, "--issues", issues) == 0
    with connect(db) as connection:
        tests, tickets = read_snapshot(connection, AS_OF)
        assert len(tests) == 5
        assert tickets[0].resolved.isoformat() == "2025-03-13"


def test_rejects_malformed_batch_without_partial_writes(lab):
    call, db, root, issues, _, first = lab
    first.write_text('<testsuite><testcase name="new"/></testsuite>', encoding="utf-8")
    issues.write_text("bad headers", encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        call("import", "--junit-dir", root, "--issues", issues)
    with connect(db) as connection:
        tests, _ = read_snapshot(connection, AS_OF)
        assert len(tests) == 7
        assert "new" not in [row["name"] for row in tests]


def test_storage_rolls_back_on_write_failure(lab):
    _, db, root, _, _, first = lab
    run = read_junit(first, root)
    run.results.append(run.results[0])
    with connect(db) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            save_import(connection, [run], [])
        tests, _ = read_snapshot(connection, AS_OF)
        assert len(tests) == 7
