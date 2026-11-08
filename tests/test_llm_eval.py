"""The model-written eval set: fixture integrity and label checks that do not use the checker.

The documents were written by a live model (evals/llm/generate.py) and labelled by reading them
before the checker was run (evals/llm/make_labels.py). These tests verify, with a small parser of
their own (not truth-gate's), that every label's evidence is really there: an injected wrong
quantity is in the document and absent from the facts, a moved quantity keeps its value and
unit, an invented tool is absent from the facts file, and a clean document uses no quantity the
facts lack. Quantities compare value AND unit: "22 months" is not the fact's "22%".
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal

import pytest
import yaml

from conftest import ROOT
from truth_gate import evals
from truth_gate.skills import Vocabulary

LLM = ROOT / "evals" / "llm"
FACTS_RAW = (ROOT / "evals" / "facts.yaml").read_text(encoding="utf-8")
FACTS = yaml.safe_load(FACTS_RAW)
_QTY = re.compile(r"(?P<cur>[$€£])?(?P<num>\d+(?:\.\d+)?)(?P<pct>\s?%|\s+percent\b)?")

# English words that open sentences in this fixture, reviewed by hand. Any other capitalised
# word must be a name from the fictional facts file, a listed skill, or the one invented tool
# named in that document's own label.
SENTENCE_OPENERS = set(
    "Additionally After As At Between Building By Demonstrating During Earlier Expanding From "
    "Furthermore Having Holding In Later Leading Leveraging Previously The These This Through To "
    "Under Using While Within".split()
)


def quantities(text: str) -> set[tuple[Decimal, str]]:
    out = set()
    for m in _QTY.finditer(text):
        kind = "money" if m.group("cur") else "percent" if m.group("pct") else "plain"
        out.add((Decimal(m.group("num")), kind))
    return out


FACT_QTY = set().union(*(quantities(f["text"]) for f in FACTS["facts"]))


def _load() -> tuple[dict[str, object], dict[str, dict[str, str]], list[dict[str, object]]]:
    lines = (LLM / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    meta = json.loads(lines[0])["meta"]
    docs = {d["id"]: d for d in map(json.loads, lines[1:])}
    labels = [
        json.loads(x) for x in (LLM / "labels.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return meta, docs, labels


META, DOCS, LABELS = _load()


def test_fixture_is_complete_and_unedited_since_labelling() -> None:
    assert "flash" in str(META["model"])
    assert [lab["id"] for lab in LABELS] == sorted(DOCS)
    for lab in LABELS:
        text = DOCS[str(lab["id"])]["document"]
        assert hashlib.sha256(text.encode()).hexdigest() == lab["doc_sha256"], lab["id"]


@pytest.mark.parametrize("lab", LABELS, ids=[str(lab["id"]) for lab in LABELS])
def test_label_evidence_holds(lab: dict[str, object]) -> None:
    doc = DOCS[str(lab["id"])]
    text, requested, evidence = doc["document"], doc["requested"], lab["evidence"]
    found = quantities(text)
    if lab["label"] == "dropped":
        assert requested != "clean"
        return
    if lab["label"] == "pass":
        assert requested == "clean"
        assert found <= FACT_QTY, found - FACT_QTY
        for phrase in FACTS["blocked_phrases"]:
            assert phrase.lower() not in text.lower()
        return
    assert isinstance(evidence, str)
    assert evidence in text
    if requested in ("wrong_number", "wrong_context"):
        assert lab["expected_check"] == "number"
        (injected,) = quantities(evidence)
        assert injected in found
        if requested == "wrong_number":
            assert injected not in FACT_QTY  # a value (or unit) the facts do not have
        else:
            assert injected in FACT_QTY  # same value and unit, attached to another claim
        assert found - {injected} <= FACT_QTY  # exactly one bad quantity
    elif requested == "invented_skill":
        assert lab["expected_check"] == "skill"
        assert evidence.lower() not in FACTS_RAW.lower()
        assert found <= FACT_QTY
    else:
        assert lab["expected_check"] == "blocked"
        assert evidence in FACTS["blocked_phrases"]
        assert found <= FACT_QTY


def test_no_names_beyond_the_fictional_setting() -> None:
    """Every capitalised word, sentence openers included, is a fictional fact name, a listed
    skill, a reviewed English sentence opener, or the invented tool in that document's label.
    Software product names (the skills list, the invented tools) are the only real names."""
    fact_names = set(re.findall(r"[A-Z][A-Za-z-]+", FACTS_RAW))
    tools = {
        str(lab["id"]): str(lab["evidence"]) for lab in LABELS if lab["expected_check"] == "skill"
    }
    for d in DOCS.values():
        allowed = fact_names | SENTENCE_OPENERS | ({tools[d["id"]]} if d["id"] in tools else set())
        for word in re.findall(r"\b[A-Z][A-Za-z-]*", d["document"]):
            assert word in allowed, (d["id"], word)


def _gate(scores: dict[str, dict[str, float]], rows: list[dict[str, object]]) -> list[str]:
    floors = json.loads((LLM / "gate.json").read_text(encoding="utf-8"))
    baseline = json.loads((LLM / "baseline.json").read_text(encoding="utf-8"))
    return evals.gate(scores, floors, baseline, rows)


def test_llm_gate_passes_and_reports_known_vocabulary_misses() -> None:
    scores, rows = evals.evaluate_llm(ROOT / "evals")
    assert _gate(scores, rows) == []
    missed = {r["id"] for r in rows if not r["ok"]}
    # Both misses are "Excel", which is not in the built-in vocabulary (see README).
    assert missed == {"L38", "L46"}
    vocab = Vocabulary(evals.load_facts(ROOT / "evals" / "facts.yaml"))
    assert "excel" not in {t.surface.lower() for t in vocab.terms}


def test_llm_gate_fails_when_skills_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Vocabulary, "find", lambda self, text: [])
    scores, rows = evals.evaluate_llm(ROOT / "evals")
    assert _gate(scores, rows)
