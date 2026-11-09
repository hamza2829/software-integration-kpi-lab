import sys

import pytest

from kpi_lab.importers import read_issues, read_junit_tree
from kpi_lab.readiness import load_milestones
from kpi_lab.synthetic import generate, main


def test_seeded_generator_produces_reproducible_importable_inputs(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setattr(sys, "argv", [
        "integration-kpi-sample", "--output", str(first), "--seed", "101", "--deliveries", "8",
    ])
    assert main() == 0
    generate(second, 101, 8)
    for path in first.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (second / path.relative_to(first)).read_bytes()
    runs = read_junit_tree(first / "junit")
    assert len(runs) == 48
    assert {run.level for run in runs} == {"unit", "integration", "system"}
    assert len(read_issues(first / "issues.csv")) == 96
    assert len(load_milestones(first / "milestones.yml")) == 8
    assert "fictional" in (first / "README.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="must be empty"):
        generate(first, 101, 8)


def test_generator_rejects_zero_deliveries(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "integration-kpi-sample", "--output", str(tmp_path / "new"), "--deliveries", "0",
    ])
    with pytest.raises(SystemExit, match="2"):
        main()
