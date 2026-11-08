"""Find quantities in text and normalise them so a document and a fact can be compared.

A quantity is a value plus a kind: plain, percent, or money with a currency. "€1.2m",
"EUR 1,200,000" and "1.2 million euros" are the same quantity; "12%" and "12" are not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

Kind = Literal["plain", "percent", "money"]

_CURRENCY = {
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "£": "GBP",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
}
_SCALE = {
    "k": Decimal(1_000),
    "thousand": Decimal(1_000),
    "m": Decimal(1_000_000),
    "mn": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "bn": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
}

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_QTY = re.compile(
    r"(?<![A-Za-z]{2}-)(?<![\w.,/])(?<!\d:)"
    r"(?P<pre>[€$£]\s?|\b(?:EUR|USD|GBP)\s?)?"
    r"(?P<num>" + _NUM + r")(?!\.\d)(?!:\d)(?!,\d)"
    r"(?:(?P<ord>st|nd|rd|th)\b"
    r"|(?P<scale>\s?(?:k|K|m|M|mn|bn)\b|\s(?:thousand|million|billion)\b))?"
    r"(?P<post>\s?%|\s(?:percent|per\s?cent)\b|\s?(?:EUR|USD|GBP)\b|\s(?:euros?|dollars?|pounds?)\b)?"
    r"(?![\w%/])"
)

_UNITS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}  # fmt: skip
_ONES = {"one": 1, **{k: v for k, v in _UNITS.items() if v < 10}}
# "one" alone is not read as a number: "one of the", "no one" are far more common in prose.
_WORDNUM = re.compile(
    r"\b(?:(?P<tens>" + "|".join(_TENS) + r")(?:-(?P<ones>" + "|".join(_ONES) + r"))?"
    r"|(?P<unit>" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r"))\b",
    re.I,
)
_RANGE_SEP = re.compile(r"^\s*(?:[-\u2013\u2014]|to)\s*$")


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    kind: Kind
    currency: str | None
    start: int
    end: int
    text: str

    def label(self) -> str:
        v = format(self.value.normalize(), "f")
        if self.kind == "percent":
            return f"{v}%"
        if self.kind == "money":
            return f"{self.currency} {v}"
        return v


def _value(num: str, scale: str | None) -> Decimal | None:
    try:
        v = Decimal(num.replace(",", ""))
    except InvalidOperation:
        return None
    if scale:
        v *= _SCALE[scale.strip().lower()]
    return v


def find_quantities(text: str) -> list[Quantity]:
    """Every quantity in `text`, in order, with offsets into `text`."""
    found: list[Quantity] = []
    for m in _QTY.finditer(text):
        value = _value(m.group("num"), m.group("scale"))
        if value is None:
            continue
        pre = (m.group("pre") or "").strip().lower()
        post = (m.group("post") or "").strip().lower()
        kind: Kind = "plain"
        currency: str | None = None
        if post in {"%", "percent"} or post.replace(" ", "") == "percent" or "cent" in post:
            kind = "percent"
        elif pre or post:
            kind = "money"
            currency = _CURRENCY.get(pre) or _CURRENCY.get(post)
        found.append(Quantity(value, kind, currency, m.start(), m.end(), m.group(0)))
    for m in _WORDNUM.finditer(text):
        if m.group("unit"):
            value = Decimal(_UNITS[m.group("unit").lower()])
        else:
            value = Decimal(_TENS[m.group("tens").lower()])
            if m.group("ones"):
                value += _ONES[m.group("ones").lower()]
        found.append(Quantity(value, "plain", None, m.start(), m.end(), m.group(0)))
    found.sort(key=lambda q: q.start)
    return _propagate_range_units(text, found)


def _propagate_range_units(text: str, qs: list[Quantity]) -> list[Quantity]:
    """In "10-15%" or "€2-3m" (any dash) unit and scale are written once; both ends get them."""
    out = list(qs)
    for i in range(len(out) - 1):
        a, b = out[i], out[i + 1]
        if not _RANGE_SEP.match(text[a.end : b.start]):
            continue
        kind, currency = a.kind, a.currency
        if kind == "plain":
            kind, currency = b.kind, b.currency
        a_value = a.value
        if _trailing_scale(a) == 1 and _trailing_scale(b) != 1:
            a_value = a.value * _trailing_scale(b)
        out[i] = Quantity(a_value, kind, currency, a.start, a.end, a.text)
        if b.kind == "plain":
            out[i + 1] = Quantity(b.value, kind, currency, b.start, b.end, b.text)
    return out


def _trailing_scale(q: Quantity) -> Decimal:
    m = re.search(r"(k|K|m|M|mn|bn|thousand|million|billion)\b", q.text)
    return _SCALE[m.group(1).lower()] if m else Decimal(1)


def same_quantity(doc: Quantity, fact: Quantity) -> bool:
    """Equal value, compatible kind.

    A plain number in the document may match money in a fact (the currency was left out, which
    is not a false claim). A percentage only matches a percentage, money only money in the
    same currency.
    """
    if doc.value != fact.value:
        return False
    if doc.kind == "plain":
        return fact.kind in ("plain", "money")
    if doc.kind == "percent":
        return fact.kind == "percent"
    return fact.kind == "money" and doc.currency == fact.currency
