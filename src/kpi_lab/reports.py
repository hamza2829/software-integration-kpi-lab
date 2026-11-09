from collections.abc import Iterable
from datetime import date
from html import escape
from importlib.resources import files
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .metrics import Delivery, KPIs, week_of
from .models import SEVERITIES
from .readiness import Readiness

TEST_HEADERS = ("Planned", "Executed", "Passed", "Failed", "Blocked",
                "Progress %", "Pass rate %", "Flaky")
ISSUE_HEADERS = (*(severity.title() for severity in SEVERITIES), "Average age (d)", "Oldest (d)")
RISK_HEADERS = ("Delivery", "Component", "Issue", "Severity", "Age (d)", "Summary", "Created")
PALETTE = ("#087d69", "#2c60a0")


def test_values(kpis: KPIs) -> tuple:
    return (kpis.planned, kpis.executed, kpis.passed, kpis.failed, kpis.blocked,
            kpis.progress_pct, kpis.pass_rate_pct, kpis.flaky)


def issue_values(kpis: KPIs) -> tuple:
    return (*(kpis.open_by_severity[severity] for severity in SEVERITIES),
            kpis.average_open_age_days, kpis.oldest_open_age_days)


def display(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def scoped(deliveries: list[Delivery]) -> Iterable[tuple[str, str, KPIs]]:
    for delivery in deliveries:
        yield delivery.name, "", delivery.kpis
        for name, kpis in delivery.components.items():
            yield delivery.name, name, kpis


def risk_rows(decisions: list[Readiness]) -> Iterable[tuple]:
    for item in decisions:
        for risk in item.risks:
            yield (risk.delivery, risk.component, risk.key, risk.severity, risk.age_days,
                   risk.summary, risk.created)


def milestone_rows(decisions: list[Readiness]) -> Iterable[tuple]:
    for item in decisions:
        for milestone in item.milestones:
            yield item.delivery, milestone.name, milestone.day


def activity_rows(deliveries: list[Delivery]) -> Iterable[tuple]:
    for delivery, component, kpis in scoped(deliveries):
        for week in kpis.weeks:
            yield delivery, component, week.starts, week.new, week.closed


def table(headers: tuple, rows: Iterable[tuple], *, compact: bool = False) -> str:
    headings = "".join(f'<th scope="col">{escape(header)}</th>' for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    if not body:
        body = f'<tr><td colspan="{len(headers)}">No records</td></tr>'
    style = ' class="compact"' if compact else ""
    return (f'<div class="scroll"><table{style}><thead><tr>{headings}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def text_rows(rows: Iterable[tuple]) -> Iterable[tuple]:
    for row in rows:
        yield tuple(escape(display(value)) for value in row)


def list_html(values: list[str]) -> str:
    if not values:
        return "None"
    return "<ul>" + "".join(f"<li>{escape(value)}</li>" for value in values) + "</ul>"


def chart(title: str, deliveries: list[Delivery],
          series: list[tuple[str, list[float | None]]], ceiling: int) -> str:
    if not deliveries:
        return f"<h3>{title}</h3><p>No deliveries with imported data.</p>"
    ticks = []
    for step in range(5):
        y = 15 + step * 30
        value = ceiling * (4 - step) / 4
        ticks.append(f'<path class="grid" d="M40 {y}H532"/><text x="4" y="{y + 4}">{value:g}</text>')
    x = [44 + 475 * index / max(1, len(deliveries) - 1) for index in range(len(deliveries))]
    every = max(1, (len(deliveries) + 7) // 8)
    for index, (delivery, position) in enumerate(zip(deliveries, x, strict=True)):
        if index % every == 0 or index == len(deliveries) - 1:
            label = escape(delivery.name.replace("Delivery-", "D")[:14])
            ticks.append(f'<text x="{position:.2f}" y="156" text-anchor="middle">{label}</text>')
    marks, legend = [], []
    for (label, values), color in zip(series, PALETTE, strict=False):
        legend.append(f'<span style="--series:{color}">{escape(label)}</span>')
        previous = None
        for delivery, position, value in zip(deliveries, x, values, strict=True):
            if value is None:
                previous = None
                continue
            y = 135 - 120 * value / ceiling
            if previous is not None:
                px, py = previous
                marks.append(f'<path stroke="{color}" stroke-width="2.5" fill="none" '
                             f'd="M{px:.2f} {py:.2f}L{position:.2f} {y:.2f}"/>')
            description = escape(f"{delivery.name}: {label} {value:.2f}")
            marks.append(f'<circle cx="{position:.2f}" cy="{y:.2f}" r="3.5" fill="{color}">'
                         f"<title>{description}</title></circle>")
            previous = position, y
    return (f'<h3>{title}</h3><svg viewBox="0 0 550 165" role="img" aria-label="{title}">'
            f'{"".join(ticks + marks)}</svg><div class="legend">{"".join(legend)}</div>')


def dashboard(deliveries: list[Delivery], decisions: list[Readiness], as_of: date,
              label: str) -> str:
    css = files("kpi_lab").joinpath("dashboard.css").read_text(encoding="utf-8")
    totals = [sum(item.kpis.open_by_severity.values()) for item in deliveries]
    go = sum(item.decision == "GO" for item in decisions)
    latest = deliveries[-1].kpis if deliveries else None
    cards = (
        ("Deliveries ready", f"{go} / {len(decisions)}"),
        ("Latest test progress", f"{latest.progress_pct:.1f}%" if latest is not None
         and latest.progress_pct is not None else "N/A"),
        ("Latest pass rate", f"{latest.pass_rate_pct:.1f}%" if latest is not None
         and latest.pass_rate_pct is not None else "N/A"),
        ("Open issues across deliveries", str(sum(totals))),
    )
    cards_html = "".join(
        f'<div class="card"><span>{name}</span><strong>{value}</strong></div>'
        for name, value in cards
    )
    health = chart("Test health (%)", deliveries, [
        ("Progress", [item.kpis.progress_pct for item in deliveries]),
        ("Pass rate", [item.kpis.pass_rate_pct for item in deliveries]),
    ], 100)
    backlog = chart("Issue backlog", deliveries, [
        ("Open issues", totals),
        ("Blocker or critical", [item.kpis.open_by_severity["blocker"] +
                                 item.kpis.open_by_severity["critical"] for item in deliveries]),
    ], max(4, ((max(totals, default=0) + 3) // 4) * 4))
    overview = table(("Delivery", *TEST_HEADERS, "Open issues"), text_rows(
        (item.name, *test_values(item.kpis), total)
        for item, total in zip(deliveries, totals, strict=True)
    ), compact=True)
    components = table(("Delivery", "Component", *TEST_HEADERS), text_rows(
        (delivery, component, *test_values(kpis))
        for delivery, component, kpis in scoped(deliveries) if component
    ), compact=True)
    issues = table(("Delivery", "Component", *ISSUE_HEADERS), text_rows(
        (delivery, component or "All components", *issue_values(kpis))
        for delivery, component, kpis in scoped(deliveries)
    ), compact=True)
    activity = table(("Delivery", "Component", "Week starts", "New", "Closed"),
                     text_rows(activity_rows(deliveries)), compact=True)
    readiness = table(("Delivery", "Decision", "Failed gates", "Milestones"), (
        (escape(item.delivery), f'<span class="badge {item.decision.lower().replace(" ", "-")}">'
         f"{item.decision}</span>", list_html(item.reasons),
         list_html([f"{milestone.day} | {milestone.name}" for milestone in item.milestones]))
        for item in decisions
    ))
    risks = table(RISK_HEADERS, text_rows(risk_rows(decisions)))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Software Integration KPI Lab</title>
<style>{css}</style>
</head>
<body>
<header>
  <div class="frame masthead"><span class="brand">SOFTWARE INTEGRATION KPI LAB</span>
    <nav aria-label="Dashboard">
      <a href="#overview">Deliveries</a><a href="#trends">Trends</a>
      <a href="#readiness">Readiness</a><a href="#risks">Risks</a>
    </nav>
  </div>
  <div class="frame hero"><p>{escape(label)} | As of {as_of}</p>
    <h1>Integration status</h1>
    <p>Test execution, issue backlog and release gates by delivery.</p>
  </div>
</header>
<main class="frame">
  <div class="cards">{cards_html}</div>
  <section id="trends"><h2>KPI trends by delivery</h2>
    <div class="charts"><div class="panel">{health}</div><div class="panel">{backlog}</div></div>
  </section>
  <section id="overview"><h2>Delivery overview</h2><div class="panel">
    {overview}
    <details><summary>Component test KPIs</summary>{components}</details>
    <details><summary>Issue severity and age by delivery and component</summary>{issues}</details>
    <details><summary>Weekly issue activity by delivery and component</summary>{activity}</details>
  </div></section>
  <section id="readiness"><h2>Release readiness</h2><div class="panel">{readiness}</div></section>
  <section id="risks"><h2>Open risks</h2><div class="panel">{risks}</div></section>
</main>
<footer class="frame">Dates are UTC. Open issue age is measured in calendar days.</footer>
</body>
</html>
"""


def md_text(value: object) -> str:
    value = escape(display(value)).replace("\n", " ").replace("\r", " ")
    for character in ("\\", "|", "*", "_", "`", "[", "]", "~"):
        value = value.replace(character, f"\\{character}")
    return value


def weekly_report(deliveries: list[Delivery], decisions: list[Readiness], as_of: date,
                  label: str) -> str:
    starts = week_of(as_of)
    lines = ["# Weekly integration status", "", md_text(label),
             f"Week of {starts}, through {as_of}", "",
             "| Delivery | Progress % | Pass rate % | New issues | Closed issues | Open issues |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for delivery in deliveries:
        kpis = delivery.kpis
        week = next((week for week in kpis.weeks if week.starts == starts), None)
        values = (delivery.name, kpis.progress_pct, kpis.pass_rate_pct,
                  week.new if week else 0, week.closed if week else 0,
                  sum(kpis.open_by_severity.values()))
        lines.append("| " + " | ".join(md_text(value) for value in values) + " |")
    lines.extend(["", "## Release readiness", ""])
    for item in decisions:
        lines.extend([f"### {md_text(item.delivery)}: {item.decision}", ""])
        lines.extend(f"- {md_text(reason)}" for reason in item.reasons)
        lines.extend(f"- {milestone.day} | {md_text(milestone.name)}"
                     for milestone in item.milestones)
        lines.append("")
    lines.extend(["## Open risks", ""])
    for delivery, component, key, severity, age, summary, _ in risk_rows(decisions):
        lines.append(f"- {md_text(delivery)} / {md_text(component)} / {md_text(key)} "
                     f"({md_text(severity)}, {age} days): {md_text(summary)}")
    return "\n".join(lines) + "\n"


def sheet(book: Workbook, name: str, headers: tuple, rows: Iterable[tuple]) -> None:
    page = book.create_sheet(name)
    page.append(headers)
    widths = [len(header) + 3 for header in headers]
    for row in rows:
        page.append(row)
        for index, (cell, value) in enumerate(zip(page[page.max_row], row, strict=True)):
            if isinstance(value, str):
                cell.data_type = "s"
            if isinstance(value, date):
                cell.number_format = "yyyy-mm-dd"
            if isinstance(value, float):
                cell.number_format = "0.00"
            widths[index] = min(68, max(widths[index], len(display(value)) + 3))
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for index, cell in enumerate(page[1], start=1):
        cell.fill = PatternFill("solid", fgColor="173E50")
        cell.font = Font(color="FFFFFF", bold=True)
        page.column_dimensions[get_column_letter(index)].width = widths[index - 1]
    page.freeze_panes = "B2"
    page.auto_filter.ref = page.dimensions


def write_reports(out: Path, deliveries: list[Delivery], decisions: list[Readiness],
                  as_of: date, label: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "dashboard.html").write_text(dashboard(deliveries, decisions, as_of, label),
                                       encoding="utf-8")
    (out / "weekly-status.md").write_text(weekly_report(deliveries, decisions, as_of, label),
                                         encoding="utf-8")
    book = Workbook()
    book.remove(book.active)
    sheet(book, "Snapshot", ("Dataset", "As of"), [(label, as_of)])
    sheet(book, "KPIs", ("Delivery", "Component", *TEST_HEADERS, *ISSUE_HEADERS), (
        (delivery, component or "All components", *test_values(kpis), *issue_values(kpis))
        for delivery, component, kpis in scoped(deliveries)
    ))
    sheet(book, "Weekly issues", ("Delivery", "Component", "Week starts", "New", "Closed"),
          activity_rows(deliveries))
    sheet(book, "Readiness", ("Delivery", "Decision", "Failed gates"),
          ((item.delivery, item.decision, "\n".join(item.reasons)) for item in decisions))
    sheet(book, "Milestones", ("Delivery", "Milestone", "Date"), milestone_rows(decisions))
    sheet(book, "Open risks", RISK_HEADERS, risk_rows(decisions))
    book.active = book["KPIs"]
    book.save(out / "integration-kpis.xlsx")
