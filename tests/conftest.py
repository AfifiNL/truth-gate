from __future__ import annotations

from pathlib import Path

import pytest

from truth_gate.checker import Checker
from truth_gate.facts import Facts, load_facts, parse_facts

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example_facts() -> Facts:
    return load_facts(ROOT / "examples" / "facts.yaml")


def make_checker(facts: list[dict[str, str]], **extra: object) -> Checker:
    raw: dict[str, object] = {"subject": "Robin Example", "facts": facts, **extra}
    return Checker(parse_facts(raw))


def fact(id_: str, text: str) -> dict[str, str]:
    return {"id": id_, "text": text, "source": "test"}
