import sys
from datetime import date
from pathlib import Path

import pytest

from kpi_lab.cli import main

AS_OF = date(2025, 3, 17)
GATES = Path(__file__).resolve().parents[1] / "config" / "gates.yml"

ISSUES = """key,summary,severity,status,created,resolved,component,delivery
LAB-1,=1+1,blocker,In Progress,2025-03-10,,Orders,D1
LAB-2,<script>alert(1)</script>,critical,To Do,2025-03-02,,Payments,D1
LAB-3,Missing audit data,major,Done,2025-03-03,2025-03-11,Orders,D1
LAB-4,Retry message,minor,Done,2025-03-17,2025-03-18,Support,D1
LAB-5,Future delivery ticket,trivial,To Do,2025-03-19,,Orders,D2
LAB-6,Time out on initial import,major,To Do,2025-03-12,,Orders,D2
LAB-7,Fix text on invoice,trivial,To Do,2025-03-14,,Orders,D2
"""


def run_file(root, relative, body):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def invoke(monkeypatch, tmp_path):
    db = tmp_path / "integration.sqlite"

    def call(*args):
        monkeypatch.setattr(sys, "argv", ["integration-kpi", "--db", str(db), *map(str, args)])
        return main()

    return call, db


@pytest.fixture
def lab(tmp_path, invoke):
    root = tmp_path / "junit"
    order = "D1/unit/Orders/"
    first = run_file(root, order + "2025-03-09T090000Z.xml", """<testsuite>
        <testcase classname="order" name="valid"/>
        <testcase classname="order" name="invalid"><failure/></testcase>
        <testcase classname="order" name="currency"><skipped/></testcase>
    </testsuite>""")
    run_file(root, order + "2025-03-10T090000Z.xml", """<testsuites><testsuite>
        <testcase classname="order" name="invalid"/>
        <testcase classname="order" name="valid"><error/></testcase>
    </testsuite></testsuites>""")
    run_file(root, "D1/integration/Payments/2025-03-11T090000Z.xml", """<testsuite>
        <testcase classname="order" name="valid"/>
    </testsuite>""")
    run_file(root, "D2/system/Orders/2025-03-16T090000Z.xml", """<testsuite>
        <testcase classname="order" name="valid"/>
    </testsuite>""")
    run_file(root, "D2/system/Orders/2025-03-18T090000Z.xml", """<testsuite>
        <testcase classname="order" name="valid"><failure/></testcase>
    </testsuite>""")
    issues = run_file(tmp_path, "issues.csv", ISSUES)
    milestones = run_file(tmp_path, "milestones.yml", """D1:
  Release review: 2025-03-20
  Integration cutoff: 2025-03-19
D3:
  Release review: 2025-03-31
""")
    call, db = invoke
    assert call("import", "--junit-dir", root, "--issues", issues) == 0
    return call, db, root, issues, milestones, first
