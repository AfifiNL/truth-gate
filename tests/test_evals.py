from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import ROOT
from truth_gate import evals
from truth_gate.checker import Checker

EVALS = ROOT / "evals"


def test_committed_cases_match_the_builder() -> None:
    r = subprocess.run([sys.executable, str(EVALS / "build_cases.py"), "--check"], check=False)
    assert r.returncode == 0, "evals/cases.jsonl is stale: run python evals/build_cases.py"


def test_gate_passes_on_the_committed_baseline() -> None:
    assert evals.run_eval(EVALS, "all", update_baseline=False, out=None) == 0


def test_every_non_hard_case_is_handled_and_hard_cases_are_reported() -> None:
    _, rows = evals.evaluate(EVALS)
    assert all(r["ok"] for r in rows if not r["hard"])
    assert any(not r["ok"] for r in rows if r["hard"])  # the known weaknesses stay visible


@pytest.mark.parametrize("sabotage", ["ignore_numbers", "ignore_context", "ignore_skills"])
def test_gate_fails_when_a_check_is_broken(sabotage: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if sabotage == "ignore_numbers":
        monkeypatch.setattr(Checker, "_numbers", lambda *a, **k: 0)
    elif sabotage == "ignore_context":
        monkeypatch.setattr(
            Checker, "_window", lambda self, *a: set().union(*self._fact_words.values())
        )
    else:
        from truth_gate.skills import Vocabulary

        monkeypatch.setattr(Vocabulary, "find", lambda self, text: [])
    scores, _ = evals.evaluate(EVALS)
    floors = json.loads((EVALS / "gate.json").read_text(encoding="utf-8"))
    baseline = json.loads((EVALS / "baseline.json").read_text(encoding="utf-8"))
    assert evals.gate(scores, floors, baseline)
