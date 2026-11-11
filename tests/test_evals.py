from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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


def test_gate_fails_on_changed_case_count_and_lost_cases() -> None:
    scores, rows = evals.evaluate(EVALS)
    floors = json.loads((EVALS / "gate.json").read_text(encoding="utf-8"))
    baseline = json.loads((EVALS / "baseline.json").read_text(encoding="utf-8"))
    assert evals.gate(scores, floors, baseline, rows) == []
    fewer = {k: dict(v) for k, v in scores.items()}
    fewer["all"]["cases"] -= 1
    assert any("cases changed" in p for p in evals.gate(fewer, floors, baseline, rows))
    # Same metrics, but a different document is now handled wrongly: still a failure.
    caught = next(r for r in rows if r["ok"] and r["kind"] != "clean")
    swapped = [dict(r, ok=not r["ok"]) if r is caught else r for r in rows]
    assert any(caught["id"] in p for p in evals.gate(scores, floors, baseline, swapped))
    unknown = [*rows, dict(rows[0], id="new-case")]
    assert any("new-case" in p for p in evals.gate(scores, floors, baseline, unknown))


def test_split_dev_never_scores_the_held_out_half(tmp_path: Path) -> None:
    import shutil

    _, rows = evals.evaluate_llm(EVALS, ("dev",))
    assert rows
    assert {r["split"] for r in rows} == {"dev"}
    # A dev-only baseline update leaves the held-out scope and outcomes untouched.
    root = tmp_path / "evals"
    shutil.copytree(EVALS, root)
    before = json.loads((root / "llm" / "baseline.json").read_text(encoding="utf-8"))
    assert evals.run_eval(root, "dev", update_baseline=True, out=None) == 0
    after = json.loads((root / "llm" / "baseline.json").read_text(encoding="utf-8"))
    assert after["heldout"] == before["heldout"]
    held = {
        k: v
        for k, v in before["outcomes"].items()
        if k in {r["id"] for r in evals.evaluate_llm(root, ("heldout",))[1]}
    }
    assert {k: after["outcomes"][k] for k in held} == held


def test_pair_corpus_is_built_from_its_script_and_only_hard_cases_miss() -> None:
    script = ROOT / "evals" / "pairs" / "build_cases.py"
    assert subprocess.run([sys.executable, str(script), "--check"], check=False).returncode == 0
    scores, rows = evals.evaluate_pairs(ROOT / "evals")
    assert scores["all"]["cases"] == len(rows) >= 50
    assert {r["market"] for r in rows} == {"nl-NL", "ar"}
    wrong = {r["id"] for r in rows if not r["ok"]}
    assert wrong == {r["id"] for r in rows if r["hard"]}
