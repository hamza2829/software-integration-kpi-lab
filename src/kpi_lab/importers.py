import csv
from datetime import UTC, date, datetime
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .models import ISSUE_COLUMNS, LEVELS, SEVERITIES, Issue, Outcome, Run, TestResult

CLOSED_STATUSES = {"closed", "done", "resolved"}


def read_junit(path: Path, root: Path) -> Run:
    try:
        delivery, level, component, filename = path.relative_to(root).parts
        if level not in LEVELS:
            raise ValueError(f"test level must be one of {', '.join(LEVELS)}")
        timestamp = datetime.strptime(filename, "%Y-%m-%dT%H%M%SZ.xml").replace(tzinfo=UTC)
        if filename != timestamp.strftime("%Y-%m-%dT%H%M%SZ.xml"):
            raise ValueError("run filename must use YYYY-MM-DDTHHMMSSZ.xml")
        document = ElementTree.parse(path, forbid_dtd=True).getroot()
        if document.tag not in {"testsuite", "testsuites"}:
            raise ValueError("expected a testsuite or testsuites root")
        results = []
        seen = set()
        for case in document.iter("testcase"):
            classname = case.get("classname", "").strip()
            name = case.get("name", "").strip()
            if not name or (classname, name) in seen:
                raise ValueError(f"missing or duplicate testcase name: {classname}.{name}")
            seen.add((classname, name))
            tags = {element.tag for element in case}
            outcome: Outcome = "passed"
            if tags & {"failure", "error"}:
                outcome = "failed"
            elif "skipped" in tags:
                outcome = "blocked"
            results.append(TestResult(classname, name, outcome))
        if not results:
            raise ValueError("JUnit file contains no testcases")
        return Run(delivery, component, level, timestamp, results)
    except (ValueError, OSError, ParseError, DefusedXmlException) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def read_junit_tree(root: Path) -> list[Run]:
    files = sorted(root.rglob("*.xml"))
    if not files:
        raise ValueError(f"{root}: no JUnit XML files found")
    return [read_junit(path, root) for path in files]


def read_issues(path: Path) -> list[Issue]:
    line = 1
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = csv.DictReader(stream, strict=True)
            headers = rows.fieldnames or []
            if set(ISSUE_COLUMNS) - set(headers) or len(headers) != len(set(headers)):
                raise ValueError(f"expected distinct headers including {', '.join(ISSUE_COLUMNS)}")
            issues = []
            seen = set()
            for row in rows:
                line = rows.line_num
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("row has the wrong number of fields")
                values = {column: row[column].strip() for column in ISSUE_COLUMNS}
                if any(not value for column, value in values.items() if column != "resolved"):
                    raise ValueError("required field is blank")
                key = values["key"]
                if key in seen:
                    raise ValueError(f"duplicate issue key {key}")
                seen.add(key)
                severity = values["severity"].lower()
                status = values["status"].lower()
                if severity not in SEVERITIES:
                    raise ValueError(f"unknown severity {severity!r}")
                created = date.fromisoformat(values["created"])
                resolved = date.fromisoformat(values["resolved"]) if values["resolved"] else None
                if (status in CLOSED_STATUSES) != (resolved is not None):
                    raise ValueError("closed status and resolved date must agree")
                if resolved is not None and resolved < created:
                    raise ValueError("resolution precedes creation")
                issues.append(Issue(key, values["summary"], severity, status, created, resolved,
                                    values["component"], values["delivery"]))
        return issues
    except (ValueError, OSError, csv.Error) as exc:
        raise ValueError(f"{path}:{line}: {exc}") from exc
