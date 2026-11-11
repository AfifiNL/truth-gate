"""Find quantities in text and normalise them so a document and a fact can be compared.

A quantity is a value, a kind (plain, percent or money), a currency for money, and an optional
unit glued to the number ("50x", "40GB", "1990s"). "€1.2m", "EUR 1,200,000" and "1.2 million
euros" are the same quantity; "12%", "12x" and "CHF 12" are three different ones.

The scanner is fail-closed: every run of digits is read as a quantity unless it falls in one of
the documented skip rules (`SKIP_RULES`); a number-like token it cannot place is never dropped
silently in any other way.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

Kind = Literal["plain", "percent", "money"]

# ISO 4217 codes recognised before or after a number ("CHF 1.2 million", "1.2 million CAD").
ISO_CODES = frozenset(
    "EUR USD GBP CHF CAD AUD NZD JPY CNY HKD SGD SEK NOK DKK ISK PLN CZK HUF RON BGN TRY "
    "INR BRL MXN ZAR AED SAR QAR KWD ILS EGP NGN KES RUB UAH KRW TWD THB MYR IDR".split()
)
_SYMBOL_PREFIX = {  # longest first when matching
    "US$": "USD", "CA$": "CAD", "AU$": "AUD", "NZ$": "NZD", "HK$": "HKD",
    "C$": "CAD", "A$": "AUD", "S$": "SGD", "R$": "BRL",
    "€": "EUR", "$": "USD", "£": "GBP", "¥": "JPY", "₹": "INR", "₩": "KRW", "₺": "TRY",
}  # fmt: skip
_CURRENCY_WORDS = {
    "euro": "EUR", "euros": "EUR", "dollar": "USD", "dollars": "USD", "pound": "GBP",
    "pounds": "GBP", "sterling": "GBP", "franc": "CHF", "francs": "CHF", "yen": "JPY",
    "rupee": "INR", "rupees": "INR", "yuan": "CNY", "renminbi": "CNY", "peso": "MXN",
    "pesos": "MXN", "krona": "SEK", "kronor": "SEK", "krone": "NOK", "kroner": "NOK",
    "lira": "TRY", "zloty": "PLN", "ruble": "RUB", "rubles": "RUB", "rouble": "RUB",
    "roubles": "RUB", "rand": "ZAR", "dirham": "AED", "dirhams": "AED", "riyal": "SAR",
    "riyals": "SAR", "shekel": "ILS", "shekels": "ILS",
}  # fmt: skip
# "5 Canadian dollars": a country adjective before a currency word names the currency.
# An adjective not listed here gives a currency that matches no fact (fail closed).
_CURRENCY_ADJECTIVES = {
    "american": "USD", "us": "USD", "canadian": "CAD", "australian": "AUD", "swiss": "CHF",
    "singapore": "SGD", "british": "GBP", "japanese": "JPY", "indian": "INR", "chinese": "CNY",
    "mexican": "MXN", "swedish": "SEK", "norwegian": "NOK", "danish": "DKK", "turkish": "TRY",
    "polish": "PLN", "russian": "RUB",
}  # fmt: skip
_SCALE_WORDS = {
    "hundred": Decimal(100),
    "thousand": Decimal(1_000),
    "million": Decimal(1_000_000),
    "billion": Decimal(1_000_000_000),
    "trillion": Decimal(1_000_000_000_000),
}
# Scale letters glued to the number: "40k", "€1.2m", "$5B", "3bn". "5m" is read as millions.
_SCALE_SUFFIX = {
    "k": Decimal(1_000),
    "K": Decimal(1_000),
    "m": Decimal(1_000_000),
    "M": Decimal(1_000_000),
    "mn": Decimal(1_000_000),
    "bn": Decimal(1_000_000_000),
    "B": Decimal(1_000_000_000),
}

_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}  # fmt: skip
_ONES = {k: v for k, v in _UNITS.items() if v < 10}

SKIP_RULES = {
    "time": "times such as 10:30",
    "slash": "numbers joined by a slash (24/7, 03/2021)",
    "version": "version strings with two or more dots (3.12.1)",
    "comma": "comma-separated digits that are not thousands groups (1,5 or 1,2,3)",
    "glued": "digits glued to a preceding letter or underscore (v2, Q3, H2O, B2B)",
    "hyphen-name": "word-hyphen-number names below four digits (COVID-19); four-digit years "
    "after a hyphen (mid-2019) ARE checked",
}

_DIGITS = re.compile(r"\d+(?:[.,:/]\d+)*")
_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_WORDNUM = re.compile(
    r"\b(?:(?P<tens>" + "|".join(_TENS) + r")(?:-(?P<ones>" + "|".join(_ONES) + r"))?"
    r"|(?P<unit>" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")"
    r"|(?P<a>a)(?=\s+(?:" + "|".join(_SCALE_WORDS) + r")\b))\b",
    re.I,
)
_SPACE_SCALE = re.compile(r"[ \t]+(" + "|".join(_SCALE_WORDS) + r")\b", re.I)
_GLUED_SCALE = re.compile(r"(mn|bn|k|K|m|M|B)(?![A-Za-z0-9])")
_ORDINAL = re.compile(r"(st|nd|rd|th)\b")
_PERCENT = re.compile(r"[ \t]?%|[ \t]+(?:percent|per[ \t]?cent|pct)\b", re.I)
_ISO_AFTER = re.compile(r"[ \t]?([A-Z]{3})\b")
_WORD_AFTER = re.compile(r"[ \t]+(?:([A-Z][A-Za-z]+)[ \t]+)?([A-Za-z]+)\b")
_GLUED_UNIT = re.compile(r"[A-Za-z]+")
_RANGE_SEP = re.compile(r"^[ \t]*[-\u2013\u2014][ \t]*$")


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    kind: Kind
    currency: str | None
    start: int
    end: int
    text: str
    unit: str | None = None
    scaled: bool = False  # a scale ("m", "million") was written on this number itself

    def label(self) -> str:
        v = format(self.value.normalize(), "f")
        if self.kind == "percent":
            return f"{v}%"
        if self.kind == "money":
            return f"{self.currency} {v}"
        return f"{v}{self.unit}" if self.unit else v

    def year_like(self) -> bool:
        return (
            self.kind == "plain"
            and self.unit is None
            and not self.scaled
            and self.value == self.value.to_integral_value()
            and 1800 <= self.value <= 2100
            and len(self.text.strip()) == 4
        )


@dataclass(frozen=True)
class Skipped:
    """A number-like token that is deliberately not checked (see SKIP_RULES)."""

    rule: str
    start: int
    end: int
    text: str


def _prefix_currency(text: str, start: int) -> tuple[str | None, int]:
    """Currency written before the number: '€', 'US$', 'CHF ' ... Returns (code, new start)."""
    head = text[max(0, start - 5) : start]
    stripped = head.rstrip(" \t")
    gap = len(head) - len(stripped)
    if gap <= 1:
        for sym in sorted(_SYMBOL_PREFIX, key=len, reverse=True):
            if stripped.endswith(sym):
                begin = start - gap - len(sym)
                if sym[0].isalpha() and begin > 0 and text[begin - 1].isalnum():
                    continue
                return _SYMBOL_PREFIX[sym], begin
        code = stripped[-3:]
        before = start - gap - 4
        if code in ISO_CODES and len(stripped) >= 3 and (before < 0 or not text[before].isalnum()):
            return code, start - gap - 3
    return None, start


def _suffix(text: str, end: int) -> tuple[Decimal, bool, Kind, str | None, str | None, int]:
    """Scale, kind, currency and unit written after the number. Returns them and the new end."""
    scale, scaled = Decimal(1), False
    if m := _GLUED_SCALE.match(text, end):
        scale, scaled, end = _SCALE_SUFFIX[m.group(1)], True, m.end()
    elif m := _ORDINAL.match(text, end):
        return Decimal(1), False, "plain", None, None, m.end()
    while m := _SPACE_SCALE.match(text, end):
        scale, scaled, end = scale * _SCALE_WORDS[m.group(1).lower()], True, m.end()
    if text.startswith("+", end):
        end += 1  # "10+ years": the claim is at least 10; the number checked is 10
    if m := _PERCENT.match(text, end):
        return scale, scaled, "percent", None, None, m.end()
    if (m := _ISO_AFTER.match(text, end)) and m.group(1) in ISO_CODES:
        return scale, scaled, "money", m.group(1), None, m.end()
    if (m := _WORD_AFTER.match(text, end)) and m.group(2).lower() in _CURRENCY_WORDS:
        currency = _CURRENCY_WORDS[m.group(2).lower()]
        if m.group(1):
            currency = _CURRENCY_ADJECTIVES.get(m.group(1).lower(), "UNKNOWN")
        return scale, scaled, "money", currency, None, m.end()
    if m := _GLUED_UNIT.match(text, end):
        # Letters glued to the number ("50x", "100ms", "40GB", "1990s") are its unit, and a
        # fact must carry the same unit. An unknown unit is never dropped.
        return scale, scaled, "plain", None, m.group(0).lower(), m.end()
    return scale, scaled, "plain", None, None, end


def _skip_rule(text: str, m: re.Match[str]) -> str | None:
    token = m.group(0)
    if ":" in token:
        return "time"
    if "/" in token:
        return "slash"
    if token.count(".") >= 2:
        return "version"
    if "," in token and not re.fullmatch(_THOUSANDS, token):
        return "comma"
    before = text[m.start() - 1] if m.start() > 0 else ""
    if before.isalpha() or before == "_":
        return "glued"
    if before == "-" and len(token) != 4:
        # A name such as "COVID-19": letters (not preceded by a digit) right before the hyphen.
        # "5k-10k" is a range, not a name: its letters belong to the number "5k".
        i = m.start() - 2
        while i >= 0 and text[i].isalpha():
            i -= 1
        if i < m.start() - 2 and (i < 0 or not text[i].isdigit()):
            return "hyphen-name"
    return None


def scan(text: str, locale: str = "en") -> tuple[list[Quantity], list[Skipped]]:
    """Every quantity in `text` (with offsets), and every number-like token deliberately skipped.

    `locale` is "en" (the default, unchanged since v0.1) or a target language of the pair check
    ("nl", "ar"), which is read by `locales.scan_target`.
    """
    if locale != "en":
        from truth_gate.locales import scan_target

        target = scan_target(text, locale)
        return target.quantities, target.skipped
    found: list[Quantity] = []
    skipped: list[Skipped] = []
    for m in _DIGITS.finditer(text):
        rule = _skip_rule(text, m)
        if rule:
            skipped.append(Skipped(rule, m.start(), m.end(), m.group(0)))
            continue
        try:
            value = Decimal(m.group(0).replace(",", ""))
        except InvalidOperation:  # pragma: no cover - _DIGITS only yields digit tokens
            skipped.append(Skipped("comma", m.start(), m.end(), m.group(0)))
            continue
        found.append(_build(text, value, m.start(), m.end()))
    for m in _WORDNUM.finditer(text):
        if m.group("a"):
            value = Decimal(1)
        elif m.group("unit"):
            value = Decimal(_UNITS[m.group("unit").lower()])
        else:
            value = Decimal(_TENS[m.group("tens").lower()])
            if m.group("ones"):
                value += _ONES[m.group("ones").lower()]
        q = _build(text, value, m.start(), m.end(), words=True)
        # "one" and "a" are only numbers with a scale word ("one million", "a thousand"):
        # "one of the reasons" and "a team" are not claims about quantities.
        if (m.group("a") or (m.group("unit") or "").lower() == "one") and not q.scaled:
            continue
        found.append(q)
    found.sort(key=lambda q: q.start)
    return _propagate_range_units(text, found), skipped


def find_quantities(text: str, locale: str = "en") -> list[Quantity]:
    return scan(text, locale)[0]


def _build(text: str, value: Decimal, start: int, end: int, words: bool = False) -> Quantity:
    currency, qstart = (None, start) if words else _prefix_currency(text, start)
    scale, scaled, kind, cur2, unit, qend = _suffix(text, end)
    if words and unit:  # "twelve" + glued letters cannot happen; keep the word alone
        unit, qend = None, end
    if currency and kind == "plain" and unit is None:
        kind = "money"
    elif kind == "money":
        currency = cur2 if currency is None or currency == cur2 else "MIXED"
    return Quantity(value * scale, kind, currency, qstart, qend, text[qstart:qend], unit, scaled)


def _propagate_range_units(
    text: str, qs: list[Quantity], unscaled: Callable[[Quantity], Decimal] | None = None
) -> list[Quantity]:
    """In "10-15%" or "€2-3m" (any dash) the unit and scale are written once; both ends get them.

    Only a dash with nothing but spaces around it makes a range ("from 500 to 2m" does not).
    Years never take a unit, and a scale is only carried over when the range stays ordered.
    """
    out = list(qs)
    for i in range(len(out) - 1):
        a, b = out[i], out[i + 1]
        if not _RANGE_SEP.match(text[a.end : b.start]) or a.year_like() or b.year_like():
            continue
        kind, currency, unit = a.kind, a.currency, a.unit
        if kind == "plain" and unit is None:
            kind, currency, unit = b.kind, b.currency, b.unit
        value, scaled = a.value, a.scaled
        if not a.scaled and b.scaled:
            scale = b.value / (unscaled(b) if unscaled else _unscaled(text, b))
            if a.value * scale <= b.value:
                value, scaled = a.value * scale, True
        out[i] = Quantity(value, kind, currency, a.start, a.end, a.text, unit, scaled)
        if b.kind == "plain" and b.unit is None:
            out[i + 1] = Quantity(b.value, kind, currency, b.start, b.end, b.text, unit, b.scaled)
    return out


def _unscaled(text: str, q: Quantity) -> Decimal:
    m = _DIGITS.search(q.text)
    if m:
        return Decimal(m.group(0).replace(",", ""))
    w = _WORDNUM.match(q.text)  # written-out number with a scale word
    if w and w.group("unit"):
        return Decimal(_UNITS[w.group("unit").lower()])
    if w and w.group("tens"):
        return Decimal(_TENS[w.group("tens").lower()]) + (
            _ONES[w.group("ones").lower()] if w.group("ones") else 0
        )
    return Decimal(1)


def same_quantity(doc: Quantity, fact: Quantity) -> bool:
    """Equal value, compatible kind.

    - percent matches only percent; money only money in the same currency;
    - a plain number may match money (the currency was left out, which is not a false claim),
      and may leave out a fact's unit ("40" for a fact's "40GB");
    - a plain number with a unit ("40GB", "50x") needs a fact with the same unit.
    """
    if doc.value != fact.value:
        return False
    if doc.kind == "percent":
        return fact.kind == "percent"
    if doc.kind == "money":
        return fact.kind == "money" and doc.currency == fact.currency
    if doc.unit is not None:
        return fact.kind == "plain" and fact.unit == doc.unit
    return fact.kind in ("plain", "money")
