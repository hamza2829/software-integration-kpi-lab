from datetime import date

import pytest
from openpyxl import load_workbook

from kpi_lab.reports import dashboard

from .conftest import AS_OF, GATES


def test_dashboard_and_weekly_status(lab, tmp_path):
    call, _, _, _, milestones, _ = lab
    out = tmp_path / "reports"
    assert call("report", "--gates", GATES, "--milestones", milestones,
                "--as-of", AS_OF, "--out", out, "--label", "Synthetic data") == 0
    html = (out / "dashboard.html").read_text(encoding="utf-8")
    for phrase in ("<svg ", "<style>", "Synthetic data", "KPI trends by delivery",
                   "Delivery overview", "Weekly issue activity", "Component test KPIs",
                   "Release readiness", "Open risks", "Integration cutoff", "LAB-1",
                   'class="badge go"', 'class="badge no-go"', "66.67", "2025-03-17"):
        assert phrase in html
    assert "<script" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "http://" not in html and "https://" not in html

    markdown = (out / "weekly-status.md").read_text(encoding="utf-8")
    assert "Week of 2025-03-17, through 2025-03-17" in markdown
    assert "| D1 | 75.00 | 66.67 | 1 | 0 | 3 |" in markdown
    assert "| D2 | 100.00 | 100.00 | 0 | 0 | 2 |" in markdown
    assert "### D2: GO" in markdown
    assert "LAB-2 (15 days)" in markdown


def test_excel_output_contains_typed_values(lab, tmp_path):
    call, _, _, _, milestones, _ = lab
    out = tmp_path / "reports"
    assert call("report", "--gates", GATES, "--milestones", milestones,
                "--as-of", AS_OF, "--out", out) == 0
    book = load_workbook(out / "integration-kpis.xlsx", data_only=False)
    assert book.sheetnames == [
        "Snapshot", "KPIs", "Weekly issues", "Readiness", "Milestones", "Open risks",
    ]
    assert book["Snapshot"]["B2"].value.date() == AS_OF
    assert book["KPIs"]["A2"].value == "D1"
    assert book["KPIs"]["C2"].value == 4
    assert book["KPIs"]["H2"].value == 75
    assert book["KPIs"]["I2"].value == pytest.approx(200 / 3)
    assert book["KPIs"]["H2"].number_format == "0.00"
    assert book["KPIs"].freeze_panes == "B2"
    assert ("D1", "Support", 0) in {
        row[:3] for row in book["KPIs"].values
    }
    assert book["Readiness"]["B2"].value == "NO GO"
    assert "Test progress" in book["Readiness"]["C2"].value
    assert book["Milestones"]["C2"].value.date() == date(2025, 3, 19)
    assert book["Weekly issues"]["C2"].value.date() == date(2025, 2, 24)
    assert book["Open risks"]["C2"].value == "LAB-1"
    assert book["Open risks"]["E2"].value == 7
    assert book["Open risks"]["F2"].value == "=1+1"
    assert book["Open risks"]["F2"].data_type == "s"
    book.close()


def test_empty_dashboard_is_readable():
    html = dashboard([], [], AS_OF, "<synthetic>")
    assert "No deliveries with imported data." in html
    assert "No records" in html
    assert "&lt;synthetic&gt;" in html


@pytest.mark.parametrize(("args", "message"), [
    (("import",), "import requires"),
    (("kpis",), "database does not exist"),
])
def test_cli_reports_usage_errors(invoke, capsys, args, message):
    call, db = invoke
    with pytest.raises(SystemExit, match="2"):
        call(*args)
    assert message in capsys.readouterr().err
    assert not db.exists()
