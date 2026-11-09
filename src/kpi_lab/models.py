from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

SEVERITIES = ("blocker", "critical", "major", "minor", "trivial")
LEVELS = ("unit", "integration", "system")

ISSUE_COLUMNS = ("key", "summary", "severity", "status", "created", "resolved", "component",
                 "delivery")

Outcome = Literal["passed", "failed", "blocked"]


@dataclass(frozen=True)
class TestResult:
    classname: str
    name: str
    outcome: Outcome


@dataclass(frozen=True)
class Run:
    delivery: str
    component: str
    level: str
    timestamp: datetime
    results: list[TestResult]


@dataclass(frozen=True)
class Issue:
    key: str
    summary: str
    severity: str
    status: str
    created: date
    resolved: date | None
    component: str
    delivery: str
