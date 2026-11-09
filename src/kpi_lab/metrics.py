import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean

from .models import SEVERITIES, Issue

Case = tuple[str, str, str, str]


@dataclass
class TestHistory:
    latest: dict[Case, str] = field(default_factory=dict)
    changed: set[Case] = field(default_factory=set)

    def add(self, case: Case, outcome: str) -> None:
        if case in self.latest and self.latest[case] != outcome:
            self.changed.add(case)
        self.latest[case] = outcome


@dataclass(frozen=True)
class Risk:
    key: str
    summary: str
    severity: str
    created: date
    age_days: int
    component: str
    delivery: str


@dataclass(frozen=True)
class Week:
    starts: date
    new: int
    closed: int


@dataclass(frozen=True)
class KPIs:
    planned: int
    executed: int
    passed: int
    failed: int
    blocked: int
    progress_pct: float | None
    pass_rate_pct: float | None
    flaky: int
    open_by_severity: dict[str, int]
    average_open_age_days: float | None
    oldest_open_age_days: int | None
    risks: list[Risk]
    weeks: list[Week]


@dataclass(frozen=True)
class Delivery:
    name: str
    first_seen: date
    kpis: KPIs
    components: dict[str, KPIs]


def week_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def calculate(history: TestHistory, issues: list[Issue], as_of: date) -> KPIs:
    outcomes = Counter(history.latest.values())
    planned = len(history.latest)
    passed, failed, blocked = (outcomes[status] for status in ("passed", "failed", "blocked"))
    executed = passed + failed

    new: Counter[date] = Counter()
    closed: Counter[date] = Counter()
    risks = []
    for issue in issues:
        new[week_of(issue.created)] += 1
        if issue.resolved is not None and issue.resolved <= as_of:
            closed[week_of(issue.resolved)] += 1
        else:
            risks.append(Risk(issue.key, issue.summary, issue.severity, issue.created,
                              (as_of - issue.created).days, issue.component, issue.delivery))
    risks.sort(key=lambda risk: (SEVERITIES.index(risk.severity), -risk.age_days, risk.key))
    severities = Counter(risk.severity for risk in risks)
    ages = [risk.age_days for risk in risks]

    return KPIs(
        planned, executed, passed, failed, blocked,
        100 * executed / planned if planned else None,
        100 * passed / executed if executed else None,
        len(history.changed), {severity: severities[severity] for severity in SEVERITIES},
        mean(ages) if ages else None, max(ages) if ages else None, risks,
        [Week(day, new[day], closed[day]) for day in sorted(new.keys() | closed.keys())],
    )


def summarize(tests: list[sqlite3.Row], issues: list[Issue], as_of: date) -> list[Delivery]:
    first_run: dict[str, date] = {}
    first_issue: dict[str, date] = {}
    tests_by_delivery: dict[str, TestHistory] = defaultdict(TestHistory)
    tests_by_component: dict[tuple[str, str], TestHistory] = defaultdict(TestHistory)
    issues_by_delivery: dict[str, list[Issue]] = defaultdict(list)
    issues_by_component: dict[tuple[str, str], list[Issue]] = defaultdict(list)
    components: dict[str, set[str]] = defaultdict(set)

    for row in tests:
        delivery, component, level, timestamp, classname, name, outcome = tuple(row)
        first_run.setdefault(delivery, date.fromisoformat(timestamp[:10]))
        components[delivery].add(component)
        case = component, level, classname, name
        tests_by_delivery[delivery].add(case, outcome)
        tests_by_component[delivery, component].add(case, outcome)
    for issue in issues:
        delivery, component = issue.delivery, issue.component
        first_issue[delivery] = min(first_issue.get(delivery, issue.created), issue.created)
        components[delivery].add(component)
        issues_by_delivery[delivery].append(issue)
        issues_by_component[delivery, component].append(issue)

    deliveries = [
        Delivery(
            name, first_run[name] if name in first_run else first_issue[name],
            calculate(tests_by_delivery[name], issues_by_delivery[name], as_of),
            {
                component: calculate(tests_by_component[name, component],
                                     issues_by_component[name, component], as_of)
                for component in sorted(group)
            },
        )
        for name, group in components.items()
    ]
    return sorted(deliveries, key=lambda delivery: (delivery.first_seen, delivery.name))
