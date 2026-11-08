from __future__ import annotations

from decimal import Decimal

import pytest

from truth_gate.numbers import SKIP_RULES, Quantity, find_quantities, same_quantity, scan


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
        ("finished 3rd", ["3"]),
        ("10+ years", ["10"]),
        ("$3.5m-a-year product", ["USD 3500000"]),
        ("in mid-2019", ["2019"]),
        ("2021-03-05", ["2021", "3", "5"]),
    ],
)
def test_find_quantities(text: str, expected: list[str]) -> None:
    assert labels(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("US$ 5m", ["USD 5000000"]),
        ("C$5m", ["CAD 5000000"]),
        ("A$5m", ["AUD 5000000"]),
        ("CHF 1.2 million", ["CHF 1200000"]),
        ("1.2 million CAD", ["CAD 1200000"]),
        ("¥300", ["JPY 300"]),
        ("€5 USD", ["MIXED 5"]),  # contradictory markers never match any fact
        ("PHP 8 is a language", ["8"]),  # not a currency code here
        ("5 Canadian dollars", ["CAD 5"]),
        ("5 Martian dollars", ["UNKNOWN 5"]),  # unknown adjective: matches no fact
        ("40 Mexican pesos", ["MXN 40"]),
    ],
)
def test_currencies_beyond_euro_dollar_pound(text: str, expected: list[str]) -> None:
    assert labels(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("twelve engineers and twenty-five clients", ["12", "25"]),
        ("three million users", ["3000000"]),
        ("12 hundred engineers", ["1200"]),
        ("one million users", ["1000000"]),
        ("a million users", ["1000000"]),
        ("two hundred thousand rows", ["200000"]),
        ("one of the reasons", []),
        ("a team", []),
    ],
)
def test_scale_words_are_never_dropped(text: str, expected: list[str]) -> None:
    assert labels(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("50x faster", ["50x"]),
        ("$5B round", ["USD 5000000000"]),
        ("100ms latency", ["100ms"]),
        ("40GB of logs", ["40gb"]),
        ("the 1990s", ["1990s"]),
    ],
)
def test_glued_units_are_checked_not_skipped(text: str, expected: list[str]) -> None:
    assert labels(text) == expected


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("at 10:30 the meeting started", "time"),
        ("24/7 support", "slash"),
        ("since 03/2021", "slash"),
        ("Python 3.12.1", "version"),
        ("a 1,5 million budget", "comma"),
        ("v2 and Q3", "glued"),
        ("COVID-19", "hyphen-name"),
    ],
)
def test_every_skip_rule_is_documented_and_reported(text: str, rule: str) -> None:
    quantities, skipped = scan(text)
    assert quantities == []
    assert {s.rule for s in skipped} == {rule}
    assert rule in SKIP_RULES


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("from 500 to 2m", ["500", "2000000"]),  # "to" is not a range marker
        ("500–2m", ["500", "2000000"]),  # 500m would not be below 2m: no scale carried over
        ("2019 – 18%", ["2019", "18%"]),  # a year never takes a unit
        ("10–15x", ["10x", "15x"]),
    ],
)
def test_range_units_only_within_real_ranges(text: str, expected: list[str]) -> None:
    assert labels(text) == expected


def test_offsets_point_at_the_number() -> None:
    text = "Saved €1.2m in 2022, US$ 40k and three million users."
    for q in find_quantities(text):
        assert text[q.start : q.end] == q.text


def q(
    value: str, kind: str = "plain", currency: str | None = None, unit: str | None = None
) -> Quantity:
    return Quantity(Decimal(value), kind, currency, 0, 0, value, unit)  # type: ignore[arg-type]


def test_same_quantity_rules() -> None:
    assert same_quantity(q("12"), q("12"))
    assert not same_quantity(q("12"), q("13"))
    # A plain number may omit a fact's currency, but not turn into a percentage.
    assert same_quantity(q("1200000"), q("1200000", "money", "EUR"))
    assert not same_quantity(q("18"), q("18", "percent"))
    assert not same_quantity(q("18", "percent"), q("18"))
    assert same_quantity(q("5", "money", "EUR"), q("5", "money", "EUR"))
    assert not same_quantity(q("5", "money", "EUR"), q("5", "money", "USD"))
    assert not same_quantity(q("5", "money", "CHF"), q("5", "money", "EUR"))
    assert not same_quantity(q("5", "money", "EUR"), q("5"))
    # Units: a unit in the document needs the same unit in the fact; leaving one out is fine.
    assert same_quantity(q("40", unit="gb"), q("40", unit="gb"))
    assert not same_quantity(q("40", unit="gb"), q("40"))
    assert not same_quantity(q("40", unit="gb"), q("40", unit="ms"))
    assert same_quantity(q("40"), q("40", unit="gb"))
