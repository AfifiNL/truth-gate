from __future__ import annotations

from pathlib import Path

import pytest

from truth_gate.facts import FactsError, load_facts, parse_facts


def test_example_facts_load() -> None:
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
        (
            {
                "subject": "x",
                "facts": [{"id": "a", "text": "t", "source": "s"}],
                "min_context_overlap": True,
            },
            "min_context_overlap",
        ),
        (
            {
                "subject": "x",
                "facts": [
                    {"id": "a", "text": "t", "source": "s", "numbers": [{"value": 1, "unit": "XX"}]}
                ],
            },
            "unit",
        ),
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


def test_duplicate_keys_are_rejected(tmp_path: Path) -> None:
    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "subject: x\nfacts:\n  - {id: a, text: t, source: s}\n"
        "blocked_phrases: [never]\nblocked_phrases: []\n",
        encoding="utf-8",
    )
    with pytest.raises(FactsError, match="duplicate key"):
        load_facts(dup)


def test_non_utf8_facts_file_is_a_facts_error(tmp_path: Path) -> None:
    bad = tmp_path / "latin1.yaml"
    bad.write_bytes("subject: caf\xe9\n".encode("latin-1"))
    with pytest.raises(FactsError, match="UTF-8"):
        load_facts(bad)
