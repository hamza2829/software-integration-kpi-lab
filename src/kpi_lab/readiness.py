from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from .metrics import Delivery, KPIs, Risk, TestHistory, calculate


@dataclass(frozen=True)
class Gates:
    min_progress_pct: float
    min_pass_rate_pct: float
    max_open_blockers: int
    max_critical_age_days: int


@dataclass(frozen=True)
class Milestone:
    name: str
    day: date


@dataclass(frozen=True)
class Readiness:
    delivery: str
    decision: str
    reasons: list[str]
    risks: list[Risk]
    milestones: list[Milestone]


def mapping(path: Path) -> dict:
    try:
        values = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(values, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return values


def load_gates(path: Path) -> Gates:
    values = mapping(path)
    expected = set(Gates.__dataclass_fields__)
    if values.keys() != expected:
        raise ValueError(f"{path}: expected gate keys {', '.join(sorted(expected))}")
    for key, value in values.items():
        if key.startswith("min_"):
            if type(value) not in (int, float) or not 0 <= value <= 100:
                raise ValueError(f"{path}: {key} must be a percentage between 0 and 100")
        elif type(value) is not int or value < 0:
            raise ValueError(f"{path}: {key} must be a nonnegative integer")
    return Gates(**values)


def load_milestones(path: Path) -> dict[str, list[Milestone]]:
    schedule = {}
    for delivery, entries in mapping(path).items():
        if not isinstance(delivery, str) or not delivery.strip() or not isinstance(entries, dict):
            raise ValueError(f"{path}: expected a mapping of delivery names to milestone mappings")
        milestones = []
        for name, day in entries.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"{path}: invalid milestone name for {delivery}")
            try:
                parsed = date.fromisoformat(str(day))
            except ValueError as exc:
                raise ValueError(f"{path}: invalid date for {delivery}/{name}") from exc
            milestones.append(Milestone(name, parsed))
        schedule[delivery] = sorted(milestones, key=lambda item: (item.day, item.name))
    return schedule


def failed_gates(kpis: KPIs, gates: Gates) -> list[str]:
    failures = []
    for label, actual, threshold in (
        ("Test progress", kpis.progress_pct, gates.min_progress_pct),
        ("Pass rate", kpis.pass_rate_pct, gates.min_pass_rate_pct),
    ):
        if actual is None:
            failures.append(f"{label} unavailable (requires at least {threshold:g}%)")
        elif actual < threshold:
            failures.append(f"{label} {actual:.2f}% is below {threshold:g}%")

    blockers = [risk.key for risk in kpis.risks if risk.severity == "blocker"]
    if len(blockers) > gates.max_open_blockers:
        failures.append(
            f"{len(blockers)} open blocker issues exceed the limit of "
            f"{gates.max_open_blockers} ({', '.join(blockers)})"
        )
    overdue = [f"{risk.key} ({risk.age_days} days)" for risk in kpis.risks
               if risk.severity == "critical" and risk.age_days > gates.max_critical_age_days]
    if overdue:
        failures.append(
            f"Open critical issues older than {gates.max_critical_age_days} days: "
            f"{', '.join(overdue)}"
        )
    return failures


def assess(deliveries: list[Delivery], gates: Gates,
           schedule: dict[str, list[Milestone]]) -> list[Readiness]:
    results = []
    for delivery in deliveries:
        reasons = failed_gates(delivery.kpis, gates)
        results.append(Readiness(delivery.name, "NO GO" if reasons else "GO", reasons,
                                 delivery.kpis.risks, schedule.get(delivery.name, [])))
    for name in sorted(schedule.keys() - {delivery.name for delivery in deliveries}):
        no_data = calculate(TestHistory(), [], date.min)
        results.append(Readiness(name, "NO GO", failed_gates(no_data, gates), [], schedule[name]))
    return results
