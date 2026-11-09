import argparse
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from .importers import read_issues, read_junit_tree
from .metrics import summarize
from .readiness import assess, load_gates, load_milestones
from .reports import write_reports
from .store import connect, read_snapshot, save_import


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Software integration reporting from local files")
    parser.add_argument("--db", type=Path, default=Path("integration.sqlite"))
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("import", help="Load JUnit runs, an issue CSV, or both")
    ingest.add_argument("--junit-dir", type=Path)
    ingest.add_argument("--issues", type=Path)
    kpis = commands.add_parser("kpis", help="Print KPI history as JSON")
    readiness = commands.add_parser("readiness", help="Print release gate decisions as JSON")
    report = commands.add_parser("report", help="Write HTML, Markdown and Excel reports")
    for command in (kpis, readiness, report):
        command.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(UTC).date())
    for command in (readiness, report):
        command.add_argument("--gates", type=Path, required=True)
        command.add_argument("--milestones", type=Path)
    report.add_argument("--out", type=Path, required=True)
    report.add_argument("--label", default="Integration workspace", help="Dataset label on reports")
    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    try:
        if args.command == "import":
            if not (args.junit_dir or args.issues):
                parser.error("import requires --junit-dir, --issues, or both")
            runs = read_junit_tree(args.junit_dir) if args.junit_dir else []
            issues = read_issues(args.issues) if args.issues else []
            with connect(args.db) as connection:
                save_import(connection, runs, issues)
            print(f"Imported {len(runs)} JUnit runs and {len(issues)} issues")
            return 0

        if not args.db.is_file():
            raise ValueError(f"{args.db}: database does not exist; import data first")
        with connect(args.db) as connection:
            deliveries = summarize(*read_snapshot(connection, args.as_of), args.as_of)

        if args.command == "kpis":
            print(json.dumps([asdict(delivery) for delivery in deliveries], default=str, indent=2))
            return 0

        gates = load_gates(args.gates)
        schedule = load_milestones(args.milestones) if args.milestones else {}
        decisions = assess(deliveries, gates, schedule)
        if args.command == "readiness":
            print(json.dumps([asdict(decision) for decision in decisions], default=str, indent=2))
        else:
            write_reports(args.out, deliveries, decisions, args.as_of, args.label)
            print(f"Wrote dashboard.html, weekly-status.md and integration-kpis.xlsx to {args.out}")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0
