"""The model-written eval set: fixture integrity and label checks that do not use the checker.

The documents were written by a live model (evals/llm/generate.py) and labelled by reading them
before the checker was run (evals/llm/make_labels.py). These tests verify, independently of
truth-gate's own parser, that every label's evidence is really there: an injected wrong number
is in the document and absent from the facts, an invented tool is absent from the facts file,
and a clean document uses no digit string the facts do not contain.
"""

from __future__ import annotations

import hashlib
import json
import re

import pytest
import yaml

from conftest import ROOT
from truth_gate import evals
from truth_gate.skills import Vocabulary

LLM = ROOT / "evals" / "llm"
FACTS_RAW = (ROOT / "evals" / "facts.yaml").read_text(encoding="utf-8")
FACTS = yaml.safe_load(FACTS_RAW)
FACT_DIGITS = set(re.findall(r"\d+(?:\.\d+)?", " ".join(f["text"] for f in FACTS["facts"])))


def _load() -> tuple[dict[str, object], dict[str, dict[str, str]], list[dict[str, object]]]:
    lines = (LLM / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    meta = json.loads(lines[0])["meta"]
    docs = {d["id"]: d for d in map(json.loads, lines[1:])}
    labels = [
        json.loads(x) for x in (LLM / "labels.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return meta, docs, labels


META, DOCS, LABELS = _load()


def test_fixture_is_complete_and_unedited() -> None:
    assert "flash" in str(META["model"])
    assert [lab["id"] for lab in LABELS] == sorted(DOCS)
    for lab in LABELS:
        text = DOCS[str(lab["id"])]["document"]
        assert hashlib.sha256(text.encode()).hexdigest() == lab["doc_sha256"], lab["id"]


@pytest.mark.parametrize("lab", LABELS, ids=[str(lab["id"]) for lab in LABELS])
def test_label_evidence_holds(lab: dict[str, object]) -> None:
    doc = DOCS[str(lab["id"])]
    text, requested, evidence = doc["document"], doc["requested"], lab["evidence"]
    digits = set(re.findall(r"\d+(?:\.\d+)?", text))
    if lab["label"] == "dropped":
        assert requested != "clean"
        return
    if lab["label"] == "pass":
        assert requested == "clean"
        assert digits <= FACT_DIGITS, digits - FACT_DIGITS
        for phrase in FACTS["blocked_phrases"]:
            assert phrase.lower() not in text.lower()
        return
    assert isinstance(evidence, str)
    assert evidence in text
    value = re.sub(r"[^\d.]", "", evidence)
    if requested == "wrong_number":
        assert lab["expected_check"] == "number"
        assert value not in FACT_DIGITS
    elif requested == "wrong_context":
        assert lab["expected_check"] == "number"
        assert value in FACT_DIGITS
    elif requested == "invented_skill":
        assert lab["expected_check"] == "skill"
        assert evidence.lower() not in FACTS_RAW.lower()
    else:
        assert lab["expected_check"] == "blocked"
        assert evidence in FACTS["blocked_phrases"]


def test_no_names_beyond_the_fictional_setting_and_tools() -> None:
    """Capitalised words that do not start a sentence are fact names, known tools or the
    invented tools recorded as label evidence: no real company, place or person."""
    allowed = set(re.findall(r"[A-Z][A-Za-z-]+", FACTS_RAW))
    allowed |= {str(lab["evidence"]) for lab in LABELS if lab["expected_check"] == "skill"}
    for d in DOCS.values():
        for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b[A-Z][A-Za-z-]+", d["document"]):
            assert m.group(0) in allowed, (d["id"], m.group(0))


def test_llm_gate_passes_and_reports_known_vocabulary_misses() -> None:
    scores, rows = evals.evaluate_llm(ROOT / "evals")
    floors = json.loads((LLM / "gate.json").read_text(encoding="utf-8"))
    baseline = json.loads((LLM / "baseline.json").read_text(encoding="utf-8"))
    assert evals.gate(scores, floors, baseline) == []
    missed = {r["id"] for r in rows if not r["ok"]}
    # Both misses are "Excel", which is not in the built-in vocabulary (see README).
    assert missed == {"L38", "L46"}
    assert "excel" not in {
        t.surface.lower() for t in Vocabulary(evals.load_facts(ROOT / "evals" / "facts.yaml")).terms
    }


def test_llm_gate_fails_when_skills_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Vocabulary, "find", lambda self, text: [])
    scores, _ = evals.evaluate_llm(ROOT / "evals")
    floors = json.loads((LLM / "gate.json").read_text(encoding="utf-8"))
    baseline = json.loads((LLM / "baseline.json").read_text(encoding="utf-8"))
    assert evals.gate(scores, floors, baseline)
