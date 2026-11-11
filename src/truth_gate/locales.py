"""Number reading and text folding for the target locales of the pair check: Dutch and Arabic.

English is read by `numbers.scan` itself and nothing here changes it. A target text is read
with the same fail-closed approach: every run of digits is a quantity unless a documented skip
rule applies. What differs per locale is in two data files (`data/nl.txt`, `data/ar.txt`):
number words, scale words, percent words, currency words and, for Arabic, the particles that
attach to a word.

Dutch: `,` is the decimal mark and `.` (or a no-break space) groups thousands, so `1.200,50`
is 1200.5 and `1,200` is 1.2. A dot that does not group thousands (`1.5`) is read as a decimal
and reported as English number format.

Arabic: the text is folded first (direction marks, diacritics and the elongation character
removed; alef forms folded to one; Arabic-Indic and Persian digits and the Arabic percent,
decimal and thousands signs mapped to their ASCII counterparts). After folding, digits are
read with the English rules.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import cache
from importlib import resources

from truth_gate.numbers import (
    _GLUED_SCALE,
    _GLUED_UNIT,
    _ISO_AFTER,
    _SCALE_SUFFIX,
    _THOUSANDS,
    ISO_CODES,
    Kind,
    Quantity,
    Skipped,
    _prefix_currency,
    _propagate_range_units,
)

SUPPORTED = ("nl", "ar")

# Unicode direction marks, embeddings and isolates: invisible, and common around a Latin name
# inside right-to-left text.
_BIDI = frozenset("\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
_TATWEEL = "\u0640"
_FOLD_AR = {
    "\u0623": "\u0627",  # alef with hamza above
    "\u0625": "\u0627",  # alef with hamza below
    "\u0622": "\u0627",  # alef with madda
    "\u0671": "\u0627",  # alef wasla
    "\u066a": "%",  # Arabic percent sign
    "\u066b": ".",  # Arabic decimal separator
    "\u066c": ",",  # Arabic thousands separator
}
_FOLD_AR.update({chr(0x0660 + i): str(i) for i in range(10)})  # Arabic-Indic digits
_FOLD_AR.update({chr(0x06F0 + i): str(i) for i in range(10)})  # Persian digits
_SP = "[ \t\u00a0]"
_NL_GROUP_SPACES = "\u00a0\u202f\u2009"
_NL_DIGITS = re.compile(r"\d+(?:[.,:/]\d+|[" + _NL_GROUP_SPACES + r"]\d{3}(?!\d))*")
_EN_DIGITS = re.compile(r"\d+(?:[.,:/]\d+)*")
_NL_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")
_NL_DECIMAL = re.compile(r"\d+,\d+")
_NL_ENGLISH_DECIMAL = re.compile(r"\d+\.\d+")


def _is_arabic_mark(ch: str) -> bool:
    return "\u064b" <= ch <= "\u0652" or ch == "\u0670"


def language_of(market: str) -> str:
    """`nl-NL` -> `nl`, `ar` -> `ar`. The language decides how a target text is read."""
    return market.split("-")[0].lower()


def fold(text: str, locale: str) -> tuple[str, list[int] | None]:
    """The text as it is matched, and for each folded character its offset in `text`.

    Dutch text is not folded (the map is None: offsets are unchanged).
    """
    if locale != "ar":
        return text, None
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch in _BIDI or ch == _TATWEEL or _is_arabic_mark(ch):
            continue
        out.append(_FOLD_AR.get(ch, ch))
        index.append(i)
    return "".join(out), index


def fold_text(text: str, locale: str) -> str:
    return fold(text, locale)[0]


def unfold(index: list[int] | None, start: int, end: int) -> tuple[int, int]:
    """Offsets in the folded text back to offsets in the original."""
    if index is None or end <= start:
        return start, end
    return index[start], index[end - 1] + 1


@dataclass(frozen=True)
class LocaleData:
    code: str
    number_words: dict[str, Decimal]
    no_particle: frozenset[str]
    needs_scale: dict[str, Decimal]
    scale_words: dict[str, Decimal]
    bare_scale: dict[str, Decimal]
    compound_units: dict[str, Decimal]
    percent_words: tuple[str, ...]
    currency_words: dict[str, str]
    ordinal_suffixes: tuple[str, ...]
    number_particles: frozenset[str]
    word_particles: tuple[str, ...]
    scale_rx: re.Pattern[str] = field(init=False, repr=False, compare=False)
    percent_rx: re.Pattern[str] = field(init=False, repr=False, compare=False)
    currency_rx: re.Pattern[str] | None = field(init=False, repr=False, compare=False)
    ordinal_rx: re.Pattern[str] | None = field(init=False, repr=False, compare=False)
    word_rx: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "scale_rx", re.compile(_SP + "+(" + _alt(self.scale_words) + r")(?!\w)", re.I))
        percent = _SP + "?%"
        if self.percent_words:
            percent += "|" + _SP + "+(?:" + _alt(self.percent_words) + r")(?!\w)"
        set_(self, "percent_rx", re.compile(percent, re.I))
        set_(
            self,
            "currency_rx",
            re.compile(_SP + "+(" + _alt(self.currency_words) + r")(?!\w)", re.I)
            if self.currency_words
            else None,
        )
        set_(
            self,
            "ordinal_rx",
            re.compile("(?:" + _alt(self.ordinal_suffixes) + r")(?!\w)")
            if self.ordinal_suffixes
            else None,
        )
        set_(self, "word_rx", self._word_pattern())

    def particle_pattern(self) -> str:
        """An optional attached particle, as a regex fragment ('' when the locale has none)."""
        return "(?:" + _alt(self.word_particles) + ")?" if self.word_particles else ""

    def _word_pattern(self) -> re.Pattern[str]:
        scale_ahead = "(?=" + _SP + "+(?:" + _alt(self.scale_words) + r")(?!\w))"
        free = [w for w in self.number_words if w not in self.no_particle]
        parts: list[str] = []
        if self.compound_units:
            tens = [w for w, v in self.number_words.items() if v >= 20 and v % 10 == 0]
            units = _alt(self.compound_units)
            # "vijfentwintig" = 5 + 20; "tweeduizend" = 2 x 1000
            parts.append(f"(?P<cu>{units})(?:en|\u00ebn)(?P<ct>{_alt(tens)})")
            parts.append(f"(?P<su>{units})(?P<ss>{_alt(self.bare_scale)})")
        if free:
            parts.append(f"{self.particle_pattern()}(?P<num>{_alt(free)})")
        if self.no_particle:
            parts.append(f"\u0648?(?P<strict>{_alt(self.no_particle)})")
        parts.append(f"{self.particle_pattern()}(?P<one>{_alt(self.needs_scale)}){scale_ahead}")
        parts.append(f"{self.particle_pattern()}(?P<bare>{_alt(self.bare_scale)})")
        return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.I)

    def word_value(self, m: re.Match[str]) -> Decimal:
        g = {k: v.lower() for k, v in m.groupdict().items() if v is not None}
        if "cu" in g:
            return self.compound_units[g["cu"]] + self.number_words[g["ct"]]
        if "su" in g:
            return self.compound_units[g["su"]] * self.bare_scale[g["ss"]]
        if "num" in g:
            return self.number_words[g["num"]]
        if "strict" in g:
            return self.number_words[g["strict"]]
        if "one" in g:
            return self.needs_scale[g["one"]]
        return self.bare_scale[g["bare"]]


def _alt(words: Iterable[str]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


def _read_sections(code: str) -> dict[str, list[tuple[str | None, list[str]]]]:
    raw = resources.files("truth_gate").joinpath("data", f"{code}.txt").read_text(encoding="utf-8")
    sections: dict[str, list[tuple[str | None, list[str]]]] = {}
    current: list[tuple[str | None, list[str]]] | None = None
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], [])
            continue
        if current is None:
            raise ValueError(f"data/{code}.txt: line outside a section: {line}")
        key: str | None = None
        if " = " in line:
            key, line = (part.strip() for part in line.split(" = ", 1))
        current.append((key, [f.strip() for f in line.split("|") if f.strip()]))
    return sections


@cache
def load(code: str) -> LocaleData:
    if code not in SUPPORTED:
        raise ValueError(f"unsupported target language: {code}")
    sections = _read_sections(code)

    def norm(form: str) -> str:
        return fold_text(form, code).lower()

    def values(name: str) -> dict[str, Decimal]:
        return {
            norm(form): Decimal(key or "0")
            for key, forms in sections.get(name, [])
            for form in forms
        }

    def flat(name: str) -> tuple[str, ...]:
        return tuple(norm(f) for _, forms in sections.get(name, []) for f in forms)

    number_words: dict[str, Decimal] = {}
    strict: set[str] = set()
    for key, forms in sections.get("number-words", []):
        for form in forms:
            word = norm(form.lstrip("="))
            number_words[word] = Decimal(key or "0")
            if form.startswith("="):
                strict.add(word)
    return LocaleData(
        code=code,
        number_words=number_words,
        no_particle=frozenset(strict),
        needs_scale=values("needs-scale"),
        scale_words=values("scale-words"),
        bare_scale=values("bare-scale"),
        compound_units=values("compound-units"),
        percent_words=flat("percent-words"),
        currency_words={
            norm(form): key or ""
            for key, forms in sections.get("currency-words", [])
            for form in forms
        },
        ordinal_suffixes=flat("ordinal-suffixes"),
        number_particles=frozenset(flat("number-particles")),
        word_particles=flat("word-particles"),
    )


@dataclass(frozen=True)
class TargetScan:
    quantities: list[Quantity]
    skipped: list[Skipped]
    english_format: list[Quantity]  # Dutch only: "1.5" where Dutch writes "1,5"


def _parse_nl(token: str) -> tuple[Decimal | None, str | None, bool]:
    """(value, skip rule, written in English format)."""
    if ":" in token:
        return None, "time", False
    if "/" in token:
        return None, "slash", False
    for sp in _NL_GROUP_SPACES:
        token = token.replace(sp, ".")
    english = False
    if _NL_THOUSANDS.fullmatch(token):
        plain = token.replace(".", "").replace(",", ".")
    elif _NL_DECIMAL.fullmatch(token):
        plain = token.replace(",", ".")
    elif token.isdigit():
        plain = token
    elif _NL_ENGLISH_DECIMAL.fullmatch(token):
        plain, english = token, True
    elif token.count(".") >= 2:
        return None, "version", False
    else:
        return None, "comma", False
    return Decimal(plain), None, english


def _parse_en(token: str) -> tuple[Decimal | None, str | None, bool]:
    if ":" in token:
        return None, "time", False
    if "/" in token:
        return None, "slash", False
    if token.count(".") >= 2:
        return None, "version", False
    if "," in token and not _THOUSANDS.fullmatch(token):
        return None, "comma", False
    try:
        return Decimal(token.replace(",", "")), None, False
    except InvalidOperation:  # pragma: no cover - the token pattern only yields digit tokens
        return None, "comma", False


def _attached(text: str, start: int, data: LocaleData) -> str | None:
    """Skip rule for digits glued to what precedes them, or None when they stand alone."""
    before = text[start - 1] if start > 0 else ""
    if before.isalpha() or before == "_":
        i = start - 1
        while i >= 0 and text[i].isalpha():
            i -= 1
        if text[i + 1 : start] in data.number_particles:
            return None  # "\u062820": an attached preposition, not a name such as "B2B"
        return "glued"
    return None


def _hyphen_name(text: str, start: int, token: str) -> bool:
    if (text[start - 1] if start > 0 else "") != "-" or len(token) == 4:
        return False
    i = start - 2
    while i >= 0 and text[i].isalpha():
        i -= 1
    return i < start - 2 and (i < 0 or not text[i].isdigit())


def _suffix(
    text: str, end: int, data: LocaleData
) -> tuple[Decimal, bool, Kind, str | None, str | None, int]:
    """Scale, kind, currency and unit written after the number, and the new end."""
    scale, scaled = Decimal(1), False
    if data.code == "nl" and (m := _GLUED_SCALE.match(text, end)):
        scale, scaled, end = _SCALE_SUFFIX[m.group(1)], True, m.end()
    elif data.ordinal_rx and (m := data.ordinal_rx.match(text, end)):
        return Decimal(1), False, "plain", None, None, m.end()
    while m := data.scale_rx.match(text, end):
        scale, scaled, end = scale * data.scale_words[m.group(1).lower()], True, m.end()
    if text.startswith("+", end):
        end += 1
    if m := data.percent_rx.match(text, end):
        return scale, scaled, "percent", None, None, m.end()
    if (m := _ISO_AFTER.match(text, end)) and m.group(1) in ISO_CODES:
        return scale, scaled, "money", m.group(1), None, m.end()
    if data.currency_rx and (m := data.currency_rx.match(text, end)):
        return scale, scaled, "money", data.currency_words[m.group(1).lower()], None, m.end()
    if m := _GLUED_UNIT.match(text, end):
        return scale, scaled, "plain", None, m.group(0).lower(), m.end()
    return scale, scaled, "plain", None, None, end


def _build(
    text: str, value: Decimal, start: int, end: int, data: LocaleData, words: bool = False
) -> Quantity:
    currency, qstart = (None, start) if words else _prefix_currency(text, start)
    scale, scaled, kind, cur2, unit, qend = _suffix(text, end, data)
    if words and unit:
        unit, qend = None, end
    if currency and kind == "plain" and unit is None:
        kind = "money"
    elif kind == "money":
        currency = cur2 if currency is None or currency == cur2 else "MIXED"
    if data.code == "ar" and kind == "plain" and unit is None and not words:
        # Arabic text often has the sign first in typing order: "%20".
        head = text[max(0, qstart - 2) : qstart]
        if head.endswith("%") or head.endswith("% "):
            kind, qstart = "percent", qstart - (1 if head.endswith("%") else 2)
    return Quantity(value * scale, kind, currency, qstart, qend, text[qstart:qend], unit, scaled)


def scan_target(text: str, locale: str) -> TargetScan:
    """Every quantity in a Dutch or Arabic text, with offsets into the text as given."""
    data = load(locale)
    folded, index = fold(text, locale)
    digits, parse = (_NL_DIGITS, _parse_nl) if locale == "nl" else (_EN_DIGITS, _parse_en)
    found: list[Quantity] = []
    skipped: list[Skipped] = []
    base: dict[int, Decimal] = {}
    english: set[int] = set()
    for m in digits.finditer(folded):
        value, rule, odd = parse(m.group(0))
        if rule is None:
            rule = _attached(folded, m.start(), data)
        if rule is None and _hyphen_name(folded, m.start(), m.group(0)):
            rule = "hyphen-name"
        if rule is not None or value is None:
            skipped.append(Skipped(rule or "comma", m.start(), m.end(), m.group(0)))
            continue
        q = _build(folded, value, m.start(), m.end(), data)
        base[q.start] = value
        if odd:
            english.add(q.start)
        found.append(q)
    taken = [(q.start, q.end) for q in found]
    for m in data.word_rx.finditer(folded):
        if any(a < m.end() and m.start() < b for a, b in taken):
            continue  # "5 miljoen": the scale word already belongs to the number before it
        value = data.word_value(m)
        q = _build(folded, value, m.start(), m.end(), data, words=True)
        base[q.start] = value
        taken.append((q.start, q.end))
        found.append(q)
    found.sort(key=lambda q: q.start)
    found = _propagate_range_units(folded, found, lambda q: base.get(q.start, q.value))

    def original(q: Quantity) -> Quantity:
        start, end = unfold(index, q.start, q.end)
        return Quantity(q.value, q.kind, q.currency, start, end, text[start:end], q.unit, q.scaled)

    return TargetScan(
        quantities=[original(q) for q in found],
        skipped=[Skipped(s.rule, *unfold(index, s.start, s.end), text=s.text) for s in skipped],
        english_format=[original(q) for q in found if q.start in english],
    )
