from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import ROOT
from truth_gate.cli import main

FACTS = str(ROOT / "examples" / "facts.yaml")


def test_check_pass_fail_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", str(ROOT / "examples" / "pass.md"), "--facts", FACTS]) == 0
    assert capsys.readouterr().out.startswith("PASS")
    assert main(["check", str(ROOT / "examples" / "fail.md"), "--facts", FACTS, "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["passed"] is False
    assert data["errors"] == 4


def test_strict_makes_warnings_fail(tmp_path: Path) -> None:
    doc = tmp_path / "d.md"
    doc.write_text("A seamless handover.", encoding="utf-8")
    assert main(["check", str(doc), "--facts", FACTS]) == 0
    assert main(["check", str(doc), "--facts", FACTS, "--strict"]) == 1


def test_bad_input_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", str(tmp_path / "nope.md"), "--facts", FACTS]) == 2
    assert main(["check", str(ROOT / "examples" / "pass.md"), "--facts", str(tmp_path / "x")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_facts_command_lists_numbers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["facts", FACTS]) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK: 6 facts about Robin Example")
    assert "budget: numbers EUR 1200000" in out
