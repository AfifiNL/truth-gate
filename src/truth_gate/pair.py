"""The pair check: a localised draft against its English source and one market's rules.

Truth flows one way: facts -> English source -> localised target. With a facts file the source
is checked by the v0.1 rules first. The target is never checked against the facts directly:
the facts are English sentences, and the context rule compares English words.

Six rules. Errors fail the pair; warnings never do.

1. number         - every quantity in the source appears in the target with the same value and
                    a compatible kind, and the target has no quantity the source lacks.
2. name           - a do-not-translate name occurs in the target, unchanged, at least as often
                    as in the source.
3. term           - when the source uses a term, the target uses one of its listed forms.
4. forbidden      - a forbidden phrase anywhere in the target fails.
5. required-line  - every required line is in the target.
6. address        - Dutch only: pronouns of the other register fail.

`format` (Dutch, a warning) marks a number written the English way ("1.5").
`source` marks a source that fails the facts check.

A finding about something missing from the target has no place in the target to point at, so
it points at the place in the source instead (`side: source`). Line 0 means the whole text.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from truth_gate.brand import Brand, Market
from truth_gate.checker import MAX_DOCUMENT_CHARS, Checker, DocumentTooLarge
from truth_gate.facts import Facts
from truth_gate.locales import fold, fold_text, language_of, load, scan_target, unfold
from truth_gate.numbers import Quantity, scan
from truth_gate.report import Report, Severity
from truth_gate.text import line_col, mask

Rule = Literal[
    "number", "format", "name", "term", "forbidden", "required-line", "address", "source"
]
# Dutch second person. A "u" inside an abbreviation such as "a.u.b." is not a pronoun.
_NL_FORMAL = re.compile(r"(?<![\w.])(?:u|uw|uzelf)(?!\w)(?!\.\w)", re.I)
_NL_INFORMAL = re.compile(r"(?<![\w.])(?:je|jij|jou|jouw|jullie)(?!\w)(?!\.\w)", re.I)


class PairFinding(BaseModel):
    rule: Rule
    severity: Severity
    side: Literal["source", "target"]
    line: int = Field(description="1-based; 0 means the whole text.")
    column: int
    text: str = Field(description="The text the finding is about.")
    message: str


class PairReport(BaseModel):
    passed: bool
    errors: int
    warnings: int
    market: str
    numbers_source: int
    numbers_target: int
    findings: list[PairFinding]
    source_report: Report | None = Field(
        default=None, description="The v0.1 report on the source, when a facts file was given."
    )

    def render(self) -> str:
        lines = [
            f"{'PASS' if self.passed else 'FAIL'} ({self.market}): {self.errors} error(s), "
            f"{self.warnings} warning(s); {self.numbers_source} number(s) in the source, "
            f"{self.numbers_target} in the target"
        ]
        for f in self.findings:
            where = f"{f.side} {f.line}:{f.column}" if f.line else f"{f.side}"
            lines.append(f"  {f.severity.upper():7} {where} {f.rule}: {f.message}")
        if self.source_report is not None and not self.source_report.passed:
            lines.append("  source against the facts:")
            lines.extend("  " + ln for ln in self.source_report.render().splitlines())
        return "\n".join(lines)


def _compatible(a: Quantity, b: Quantity) -> bool:
    """A percentage must stay a percentage. A currency or a unit may be written in words the
    scanner does not know, so money or a unit on one side may be a plain number on the other."""
    if a.kind == "percent" or b.kind == "percent":
        return a.kind == b.kind
    if a.kind == "money" and b.kind == "money":
        return a.currency == b.currency
    return not (a.unit and b.unit and a.unit != b.unit)


def _identical(a: Quantity, b: Quantity) -> bool:
    return a.kind == b.kind and a.currency == b.currency and a.unit == b.unit


def _paragraph_of(text: str) -> list[int]:
    """Paragraph number (0-based) for every character offset; blank lines separate paragraphs."""
    out: list[int] = []
    n, in_blank = -1, True
    for line in text.split("\n"):
        if line.strip():
            n += in_blank
            in_blank = False
        else:
            in_blank = True
        out.extend([max(n, 0)] * (len(line) + 1))
    return out


def _count_paragraphs(text: str) -> int:
    return max(_paragraph_of(text), default=-1) + 1 if text.strip() else 0


class PairChecker:
    def __init__(self, brand: Brand, market: str, facts: Facts | None = None):
        self.brand = brand
        self.market_name = market
        self.market: Market = brand.market(market)
        self.lang = language_of(market)
        self.facts = facts
        self._data = load(self.lang)
        particle = self._data.particle_pattern()
        tail = r"(?:s)?" if self.lang == "nl" else ""  # Dutch genitive: "ExampleFreights portaal"
        self._names = [
            (
                name,
                re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)"),
                re.compile(
                    r"(?<!\w)" + particle + re.escape(fold_text(name, self.lang)) + tail + r"(?!\w)"
                ),
            )
            for name in brand.do_not_translate
        ]
        self._terms = [
            (
                term.source,
                term.target,
                re.compile(
                    r"(?<!\w)(?:"
                    + "|".join(self._phrase(s, "en") for s in term.source)
                    + r")(?:s|es)?(?!\w)",
                    re.I,
                ),
                re.compile(
                    r"(?<!\w)"
                    + particle
                    + "(?:"
                    + "|".join(self._phrase(t, self.lang) for t in term.target)
                    + r")(?!\w)",
                    re.I,
                ),
            )
            for term in self.market.terms
        ]
        self._forbidden = [
            (
                phrase,
                re.compile(
                    r"(?<!\w)" + particle + self._phrase(phrase, self.lang) + r"(?!\w)", re.I
                ),
            )
            for phrase in self.market.forbidden
        ]

    @staticmethod
    def _phrase(phrase: str, lang: str) -> str:
        return re.escape(fold_text(phrase.strip(), lang)).replace(r"\ ", r"\s+")

    def check(self, source: str, target: str) -> PairReport:
        for name, doc in (("source", source), ("target", target)):
            if len(doc) > MAX_DOCUMENT_CHARS:
                raise DocumentTooLarge(
                    f"the {name} has {len(doc):,} characters; the limit is {MAX_DOCUMENT_CHARS:,}"
                )
        findings: list[PairFinding] = []
        source_report: Report | None = None
        if self.facts is not None:
            source_report = Checker(self.facts).check(source)
            if not source_report.passed:
                findings.append(
                    PairFinding(
                        rule="source",
                        severity="error",
                        side="source",
                        line=0,
                        column=0,
                        text="",
                        message=f"the source fails the facts check with "
                        f"{source_report.errors} error(s)",
                    )
                )
        n_source, n_target = self._numbers(source, target, findings)
        folded, index = fold(target, self.lang)
        self._names_rule(source, folded, findings)
        self._terms_rule(source, folded, findings)
        for phrase, rx in self._forbidden:
            for m in rx.finditer(folded):
                start, end = unfold(index, m.start(), m.end())
                line, col = line_col(target, start)
                findings.append(
                    PairFinding(
                        rule="forbidden",
                        severity="error",
                        side="target",
                        line=line,
                        column=col,
                        text=target[start:end],
                        message=f"forbidden phrase '{phrase}'",
                    )
                )
        flat = " ".join(folded.split()).casefold()
        for required in self.market.required_lines:
            if " ".join(fold_text(required, self.lang).split()).casefold() not in flat:
                findings.append(
                    PairFinding(
                        rule="required-line",
                        severity="error",
                        side="target",
                        line=0,
                        column=0,
                        text=required,
                        message=f"required line is missing: '{required}'",
                    )
                )
        self._address(target, findings)
        findings.sort(key=lambda f: (f.side, f.line == 0, f.line, f.column, f.rule))
        errors = sum(f.severity == "error" for f in findings)
        return PairReport(
            passed=errors == 0,
            errors=errors,
            warnings=len(findings) - errors,
            market=self.market_name,
            numbers_source=n_source,
            numbers_target=n_target,
            findings=findings,
            source_report=source_report,
        )

    def _numbers(self, source: str, target: str, findings: list[PairFinding]) -> tuple[int, int]:
        src = scan(mask(source))[0]
        tgt_scan = scan_target(mask(target), self.lang)
        tgt = tgt_scan.quantities
        left_s = list(range(len(src)))
        left_t = list(range(len(tgt)))
        for same in (_identical, _compatible):
            for i in list(left_s):
                j = next(
                    (j for j in left_t if tgt[j].value == src[i].value and same(src[i], tgt[j])),
                    None,
                )
                if j is not None:
                    left_s.remove(i)
                    left_t.remove(j)
        aligned = _count_paragraphs(source) == _count_paragraphs(target)
        para_s = _paragraph_of(source) if aligned else []
        para_t = _paragraph_of(target) if aligned else []
        explained: set[int] = set()
        for j in left_t:
            t = tgt[j]
            line, col = line_col(target, t.start)
            hint = ""
            partner = self._partner(
                t, [i for i in left_s if i not in explained], src, para_s, para_t
            )
            if partner is not None:
                explained.add(partner)
                s = src[partner]
                s_line, _ = line_col(source, s.start)
                hint = f"; the source has {s.label()} (line {s_line})"
                if s.value == t.value:
                    hint += ": the kind changed"
                elif self.lang == "nl" and s.value == t.value * 1000:
                    hint += f": in Dutch '{t.text.strip()}' has a decimal comma"
            findings.append(
                PairFinding(
                    rule="number",
                    severity="error",
                    side="target",
                    line=line,
                    column=col,
                    text=t.text,
                    message=f"{t.label()} is not in the source{hint}",
                )
            )
        for i in left_s:
            if i in explained:
                continue
            s = src[i]
            line, col = line_col(source, s.start)
            findings.append(
                PairFinding(
                    rule="number",
                    severity="error",
                    side="source",
                    line=line,
                    column=col,
                    text=s.text,
                    message=f"{s.label()} is missing from the target",
                )
            )
        for q in tgt_scan.english_format:
            line, col = line_col(target, q.start)
            findings.append(
                PairFinding(
                    rule="format",
                    severity="warning",
                    side="target",
                    line=line,
                    column=col,
                    text=q.text,
                    message=f"'{q.text.strip()}' is English number format; Dutch writes a "
                    "decimal comma",
                )
            )
        return len(src), len(tgt)

    @staticmethod
    def _partner(
        t: Quantity,
        candidates: list[int],
        src: list[Quantity],
        para_s: list[int],
        para_t: list[int],
    ) -> int | None:
        """The unmatched source number this unmatched target number most likely replaced."""
        for i in candidates:  # same value, another kind ("20%" became "20")
            if src[i].value == t.value:
                return i
        for i in candidates:  # a thousand times off: read in the other language's format
            if src[i].value in (t.value * 1000, t.value / Decimal(1000)):
                return i
        if para_s:
            same = [i for i in candidates if para_s[src[i].start] == para_t[t.start]]
            if len(same) == 1:
                return same[0]
        return None

    def _names_rule(self, source: str, folded: str, findings: list[PairFinding]) -> None:
        for name, in_source, in_target in self._names:
            hits = list(in_source.finditer(source))
            have = len(in_target.findall(folded))
            if len(hits) > have:
                line, col = line_col(source, hits[0].start())
                findings.append(
                    PairFinding(
                        rule="name",
                        severity="error",
                        side="source",
                        line=line,
                        column=col,
                        text=name,
                        message=f"'{name}' must stay as written: {len(hits)} time(s) in the "
                        f"source, {have} in the target",
                    )
                )

    def _terms_rule(self, source: str, folded: str, findings: list[PairFinding]) -> None:
        for sources, targets, in_source, in_target in self._terms:
            m = in_source.search(source)
            if m is None or in_target.search(folded):
                continue
            line, col = line_col(source, m.start())
            findings.append(
                PairFinding(
                    rule="term",
                    severity="error",
                    side="source",
                    line=line,
                    column=col,
                    text=m.group(0),
                    message=f"the source says '{sources[0]}'; the target has none of: "
                    + ", ".join(targets),
                )
            )

    def _address(self, target: str, findings: list[PairFinding]) -> None:
        if self.market.address is None:
            return
        wrong = _NL_FORMAL if self.market.address == "informal" else _NL_INFORMAL
        for n, m in enumerate(wrong.finditer(mask(target))):
            if n == 20:  # enough to act on; the rest are the same mistake
                break
            line, col = line_col(target, m.start())
            findings.append(
                PairFinding(
                    rule="address",
                    severity="error",
                    side="target",
                    line=line,
                    column=col,
                    text=m.group(0),
                    message=f"'{m.group(0)}' is {'formal' if wrong is _NL_FORMAL else 'informal'}"
                    f"; this market is addressed {self.market.address}ly",
                )
            )
