from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import ROOT
from truth_gate.checker import MAX_DOCUMENT_CHARS
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


def test_non_utf8_and_oversize_documents_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    latin = tmp_path / "latin1.md"
    latin.write_bytes("caf\xe9".encode("latin-1"))
    assert main(["check", str(latin), "--facts", FACTS]) == 2
    assert "not valid UTF-8" in capsys.readouterr().err
    big = tmp_path / "big.md"
    big.write_text("x" * (MAX_DOCUMENT_CHARS + 1), encoding="utf-8")
    assert main(["check", str(big), "--facts", FACTS]) == 2
    assert "limit" in capsys.readouterr().err
    bad_facts = tmp_path / "f.yaml"
    bad_facts.write_bytes(b"\xff\xfe")
    assert main(["check", str(ROOT / "examples" / "pass.md"), "--facts", str(bad_facts)]) == 2
