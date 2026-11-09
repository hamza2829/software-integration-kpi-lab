"""Create deterministic, fictional integration lab inputs."""

import argparse
import csv
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from random import Random
from xml.etree import ElementTree as ET

from .models import ISSUE_COLUMNS

START = date(2025, 3, 3)
SCOPES = {
    ("unit", "Order API"): (
        "order_validation",
        ("accepts_valid_cart", "rejects_empty_cart", "rejects_negative_quantity",
         "requires_customer_id", "caps_line_items", "rejects_duplicate_sku",
         "rounds_sales_tax", "preserves_currency", "normalizes_sku", "validates_coupon",
         "rejects_expired_coupon", "handles_free_shipping", "calculates_subtotal",
         "rejects_unknown_country", "limits_address_length", "masks_customer_email",
         "normalizes_postal_code", "rejects_unsupported_currency"),
    ),
    ("integration", "Payment Gateway"): (
        "gateway_contract",
        ("authorizes_card", "declines_expired_card", "retries_timeout",
         "deduplicates_callback", "validates_signature", "rejects_unsigned_callback",
         "captures_authorization", "voids_authorization", "refunds_partial_amount",
         "rejects_over_refund", "reconciles_batch", "persists_provider_reference",
         "maps_rate_limit", "maps_service_unavailable", "rejects_duplicate_capture",
         "reports_callback_lag", "redacts_card_number", "traces_provider_error"),
    ),
    ("system", "Shipment Worker"): (
        "fulfillment_journey",
        ("ships_paid_order", "holds_unpaid_order", "handles_carrier_outage",
         "resumes_from_dead_letter", "avoids_duplicate_label", "tracks_split_shipment",
         "updates_tracking_link", "handles_address_correction", "emits_dispatch_event",
         "stores_delivery_receipt", "handles_canceled_order", "retries_label_print",
         "routes_international_order", "prioritizes_express_order", "handles_pickup",
         "skips_unavailable_inventory", "releases_backorder", "matches_manifest_total"),
    ),
}
FINAL_OUTCOMES = [(5, 6), (3, 4), (1, 2), (2, 1), (1, 0), (0, 0)]
ISSUE_CATALOG = {
    "Order API": ("Coupon total rounds incorrectly for split tax",
                  "Postal code validation drops leading zeros",
                  "Duplicate SKU error omits the affected cart line",
                  "Order response exposes a retired field"),
    "Payment Gateway": ("Duplicate callback can capture the same authorization twice",
                        "Reconciliation ignores late partial refunds",
                        "Provider timeout leaves authorization state unknown",
                        "Decline response has inconsistent retry hints"),
    "Shipment Worker": ("Worker skips labels after reconnecting to the broker",
                        "Carrier retry moves valid shipments to dead letter",
                        "Tracking links are missing for split shipments",
                        "Manifest export truncates long carrier references"),
}


def write_run(path: Path, timestamp: datetime, classname: str,
              cases: list[tuple[str, str]]) -> None:
    suite = ET.Element(
        "testsuite",
        {
            "name": f"synthetic.{classname}",
            "timestamp": timestamp.isoformat(),
            "tests": str(len(cases)),
            "failures": str(sum(outcome == "failed" for _, outcome in cases)),
            "skipped": str(sum(outcome == "blocked" for _, outcome in cases)),
            "errors": "0",
        },
    )
    for name, outcome in cases:
        case = ET.SubElement(suite, "testcase", name=f"test_{name}", classname=classname)
        if outcome == "failed":
            ET.SubElement(case, "failure", message="Synthetic regression in expected result")
        elif outcome == "blocked":
            ET.SubElement(case, "skipped", message="Synthetic test dependency unavailable")
    ET.indent(suite)
    path.mkdir(parents=True, exist_ok=True)
    filename = timestamp.strftime("%Y-%m-%dT%H%M%SZ.xml")
    (path / filename).write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- Synthetic sample data -->\n" + ET.tostring(suite, encoding="unicode") + "\n",
        encoding="utf-8",
        newline="\n",
    )


def generate(root: Path, seed: int, deliveries: int) -> None:
    if deliveries < 1:
        raise ValueError("delivery count must be positive")
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError(f"{root}: output directory must be empty")
    random = Random(seed)
    issues = []
    milestones = ["# Synthetic milestone dates"]
    for number in range(1, deliveries + 1):
        delivery = f"Delivery-{number:02d}"
        monday = START + timedelta(weeks=number - 1)
        outcomes = FINAL_OUTCOMES[min(number, len(FINAL_OUTCOMES)) - 1]
        cases = [(level, component, name) for (level, component), (_, names) in SCOPES.items()
                 for name in names]
        for offset, hour, counts in [(0, 9, (outcomes[0] + 2, outcomes[1] + 3)), (3, 15, outcomes)]:
            failed, blocked = counts
            changed = random.sample(cases, failed + blocked)
            timestamp = datetime.combine(monday + timedelta(days=offset), time(hour), tzinfo=UTC)
            for (level, component), (classname, names) in SCOPES.items():
                run = []
                for name in names:
                    identity = level, component, name
                    if identity in changed[:failed]:
                        outcome = "failed"
                    elif identity in changed[failed:]:
                        outcome = "blocked"
                    else:
                        outcome = "passed"
                    run.append((name, outcome))
                write_run(root / "junit" / delivery / level / component, timestamp, classname, run)

        for component, summaries in ISSUE_CATALOG.items():
            for index, summary in enumerate(summaries):
                severity = ("critical", "major", "minor", "trivial")[index]
                if number == 1 and component == "Payment Gateway" and index == 0:
                    severity = "blocker"
                created = monday + timedelta(days=random.randint(-4, 2))
                if severity == "critical" and number in {2, 4} and component == "Shipment Worker":
                    created = monday - timedelta(days=21)
                leave_open = (
                    severity == "blocker"
                    or (severity == "critical" and number in {2, 4}
                        and component == "Shipment Worker")
                    or (severity in {"major", "minor"} and random.random() < 0.4)
                )
                resolved = "" if leave_open else created + timedelta(days=random.randint(1, 3))
                status = random.choice(["To Do", "In Progress", "Reopened"]) if leave_open else "Done"
                issues.append((f"SYN-{1001 + len(issues)}", summary, severity, status,
                               created, resolved, component, delivery))
        milestones.extend([
            f"{delivery}:",
            f"  Integration cutoff: {monday + timedelta(days=2)}",
            f"  Release review: {monday + timedelta(days=4)}",
        ])

    with (root / "issues.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(ISSUE_COLUMNS)
        writer.writerows(issues)
    (root / "milestones.yml").write_text("\n".join(milestones) + "\n", encoding="utf-8")
    (root / "README.md").write_text(
        f"# Synthetic sample data\n\nGenerated with seed {seed} for {deliveries} deliveries.\n"
        "All deliveries, tests, issues and milestone dates are fictional.\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=2829)
    parser.add_argument("--deliveries", type=int, default=6)
    args = parser.parse_args()
    try:
        generate(args.output, args.seed, args.deliveries)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0
