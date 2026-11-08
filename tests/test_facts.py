from __future__ import annotations

from pathlib import Path

import pytest

from truth_gate.facts import FactsError, load_facts, parse_facts


def test_example_facts_load(tmp_path: Path) -> None:
    facts = load_facts(Path(__file__).resolve().parents[1] / "examples" / "facts.yaml")
    assert facts.subject == "Robin Example"
    assert [s.name for s in facts.skills][:2] == ["Python", "PostgreSQL"]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([], "mapping"),
        ({"subject": "x", "facts": []}, "facts"),
        ({"subject": "x", "facts": [{"id": "a", "text": "t", "source": "s"}] * 2}, "duplicate"),
        ({"subject": "x", "facts": [{"id": "a", "text": "t"}]}, "source"),
        ({"subject": "x", "facts": [{"id": "a", "text": "t", "source": "s"}], "typo": 1}, "typo"),
    ],
)
def test_invalid_facts_are_rejected(raw: object, message: str) -> None:
    with pytest.raises(FactsError, match=message):
        parse_facts(raw)


def test_unreadable_and_invalid_yaml(tmp_path: Path) -> None:
    with pytest.raises(FactsError, match="cannot read"):
        load_facts(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("subject: [unclosed", encoding="utf-8")
    with pytest.raises(FactsError, match="not valid YAML"):
        load_facts(bad)
