from __future__ import annotations

from decimal import Decimal

import pytest

from truth_gate.numbers import Quantity, find_quantities, same_quantity


def labels(text: str) -> list[str]:
    return [q.label() for q in find_quantities(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a team of 12 engineers", ["12"]),
        ("from 2019 to 2023", ["2019", "2023"]),
        ("from 2019–2023", ["2019", "2023"]),
        ("cut costs by 18%", ["18%"]),
        ("cut costs by 18 percent", ["18%"]),
        ("cut costs by 18 per cent", ["18%"]),
        ("a 10–15% rise", ["10%", "15%"]),
        ("€1.2m", ["EUR 1200000"]),
        ("EUR 1,200,000", ["EUR 1200000"]),
        ("1.2 million euros", ["EUR 1200000"]),
        ("€2–3m", ["EUR 2000000", "EUR 3000000"]),
        ("$40k", ["USD 40000"]),
        ("$5k-10k", ["USD 5000", "USD 10000"]),
        ("£300", ["GBP 300"]),
        ("1.2 million", ["1200000"]),
        ("twelve engineers and twenty-five clients", ["12", "25"]),
        ("one of the reasons", []),
        ("finished 3rd", ["3"]),
        ("Python 3.12.1 is a version string", []),
        ("COVID-19 and v2 are names", []),
        ("at 10:30 the meeting started", []),
        ("24/7 support since 03/2021", []),
        ("a 1,5 million budget", []),
    ],
)
def test_find_quantities(text: str, expected: list[str]) -> None:
    assert labels(text) == expected


def test_offsets_point_at_the_number() -> None:
    text = "Saved €1.2m in 2022."
    for q in find_quantities(text):
        assert text[q.start : q.end] == q.text


def q(value: str, kind: str = "plain", currency: str | None = None) -> Quantity:
    return Quantity(Decimal(value), kind, currency, 0, 0, value)  # type: ignore[arg-type]


def test_same_quantity_rules() -> None:
    assert same_quantity(q("12"), q("12"))
    assert not same_quantity(q("12"), q("13"))
    # A plain number may omit a fact's currency, but not turn into a percentage.
    assert same_quantity(q("1200000"), q("1200000", "money", "EUR"))
    assert not same_quantity(q("18"), q("18", "percent"))
    assert not same_quantity(q("18", "percent"), q("18"))
    assert same_quantity(q("5", "money", "EUR"), q("5", "money", "EUR"))
    assert not same_quantity(q("5", "money", "EUR"), q("5", "money", "USD"))
    assert not same_quantity(q("5", "money", "EUR"), q("5"))
