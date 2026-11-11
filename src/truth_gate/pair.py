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

Both texts are first put in Unicode NFC and stripped of invisible characters (soft hyphen,
zero-width space and joiners, word joiner, byte-order mark), so a phrase cannot hide behind
them. Lines never change; a column counts the characters that are left.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from truth_gate.brand import Brand, Market
from truth_gate.checker import MAX_DOCUMENT_CHARS, Checker, DocumentTooLarge
from truth_gate.facts import Facts
from truth_gate.locales import (
    fold,
    fold_text,
    language_of,
    load,
    phrase_pattern,
    scan_target,
    term_pattern,
    unfold,
)
from truth_gate.numbers import Quantity, Skipped, scan
from truth_gate.report import Report, Severity
from truth_gate.text import line_col, mask

Rule = Literal[
    "number", "format", "name", "term", "forbidden", "required-line", "address", "source"
]
# Dutch second person. A "u" inside an abbreviation such as "a.u.b." is not a pronoun.
_NL_FORMAL = re.compile(r"(?<![\w.])(?:u|uw|uzelf)(?!\w)(?!\.\w)", re.I)
_NL_INFORMAL = re.compile(
    r"(?<![\w.])(?:je|jij|jou|jouw|jullie|jezelf|jijzelf)(?!\w)(?!\.\w)", re.I
)
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"))
_DECORATION = " \t*_>#-"
_TOKEN_WORD = re.compile(r"[\w.:/,-]*")


def clean(text: str) -> str:
    """NFC, without invisible characters."""
    return unicodedata.normalize("NFC", text).translate(_INVISIBLE)


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
                re.compile(r"(?<!\w)" + re.escape(clean(name)) + r"(?!\w)"),
                re.compile(
                    r"(?<!\w)"
                    + particle
                    + re.escape(fold_text(clean(name), self.lang))
                    + tail
                    + r"(?!\w)"
                ),
            )
            for name in brand.do_not_translate
        ]
        self._terms = [
            (
                term.source,
                term.target,
                re.compile(
                    r"(?<!\w)(?:" + "|".join(map(self._source_term, term.source)) + r")(?!\w)",
                    re.I,
                ),
                re.compile(
                    r"(?<!\w)"
                    + particle
                    + "(?:"
                    + "|".join(term_pattern(clean(t), self._data) for t in term.target)
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
                    r"(?<!\w)" + particle + phrase_pattern(clean(phrase), self._data) + r"(?!\w)",
                    re.I,
                ),
            )
            for phrase in self.market.forbidden
        ]

    @staticmethod
    def _source_term(term: str) -> str:
        """An English term, singular or plural: shipment(s), box(es), delivery/deliveries."""
        words = [re.escape(w) for w in term.split()]
        last = term.split()[-1]
        if len(last) > 2 and last[-1] in "yY" and last[-2].lower() not in "aeiou":
            words[-1] = re.escape(last[:-1]) + "(?:y|ies)"
        else:
            words[-1] += "(?:s|es)?"
        return r"\s+".join(words)

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
        source, target = clean(source), clean(target)
        masked_source, masked_target = mask(source), mask(target)
        n_source, n_target = self._numbers(source, target, masked_source, masked_target, findings)
        folded, index = fold(target, self.lang)
        folded_masked = fold_text(masked_target, self.lang)
        self._names_rule(source, masked_source, folded_masked, findings)
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
        present = self._lines_and_paragraphs(folded_masked)
        for required in self.market.required_lines:
            if self._flat(fold_text(clean(required), self.lang)) not in present:
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
        self._address(target, masked_target, findings)
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

    @staticmethod
    def _flat(text: str) -> str:
        return " ".join(text.strip(_DECORATION).split()).casefold()

    @classmethod
    def _lines_and_paragraphs(cls, text: str) -> set[str]:
        """Every line and every paragraph, without Markdown decoration: a required line must
        stand as one of them, not inside another sentence or a comment."""
        out: set[str] = set()
        paragraph: list[str] = []
        for line in [*text.split("\n"), ""]:
            if line.strip():
                out.add(cls._flat(line))
                paragraph.append(line)
            elif paragraph:
                out.add(cls._flat(" ".join(paragraph)))
                paragraph = []
        return out

    def _numbers(
        self,
        source: str,
        target: str,
        masked_source: str,
        masked_target: str,
        findings: list[PairFinding],
    ) -> tuple[int, int]:
        src, src_skipped = scan(masked_source)
        tgt_scan = scan_target(masked_target, self.lang)
        tgt = tgt_scan.quantities
        # Match by value through an index, so the cost does not grow with the square of the
        # number of quantities: identical kinds first, then compatible ones.
        by_value: dict[Decimal, list[int]] = defaultdict(list)
        for j, t in enumerate(tgt):
            by_value[t.value].append(j)
        matched_t: set[int] = set()
        left_s = list(range(len(src)))
        for same in (_identical, _compatible):
            still: list[int] = []
            for i in left_s:
                bucket = by_value.get(src[i].value, [])
                hit = next((k for k in bucket if same(src[i], tgt[k])), None)
                if hit is None:
                    still.append(i)
                else:
                    bucket.remove(hit)
                    matched_t.add(hit)
            left_s = still
        left_t = [j for j in range(len(tgt)) if j not in matched_t]
        aligned = _count_paragraphs(source) == _count_paragraphs(target)
        para_s = _paragraph_of(source) if aligned else []
        para_t = _paragraph_of(target) if aligned else []
        open_s = _Open(src, left_s, para_s)
        for j in left_t:
            t = tgt[j]
            line, col = line_col(target, t.start)
            hint = ""
            partner = open_s.take(t, para_t[t.start] if para_t else None)
            if partner is not None:
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
        for i in open_s.remaining():
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
        self._tokens(source, target, masked_source, src_skipped, tgt_scan.skipped, findings)
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

    def _tokens(
        self,
        source: str,
        target: str,
        masked_source: str,
        src_skipped: list[Skipped],
        tgt_skipped: list[Skipped],
        findings: list[PairFinding],
    ) -> None:
        """Number-like tokens the scanner does not read as quantities (times, 24/7, versions,
        names such as Q3 or B2B) must be the same on both sides, compared as text."""
        folded_target, index = fold(mask(target), self.lang)

        def keyed(
            text: str, skipped: list[Skipped], fold_index: list[int] | None
        ) -> list[tuple[str, int]]:
            out = []
            for s in skipped:
                start = s.start
                if fold_index is not None:  # offsets are in the original; find the folded one
                    start = _folded_offset(fold_index, s.start)
                lo = start
                while lo > 0 and (text[lo - 1].isalnum() or text[lo - 1] in "-_"):
                    lo -= 1
                m = _TOKEN_WORD.match(text, start)
                word = text[lo : m.end() if m else start].rstrip(".,:/-")
                out.append((word.casefold(), s.start))
            return out

        src_keys = keyed(masked_source, src_skipped, None)
        tgt_keys = keyed(folded_target, tgt_skipped, index)
        want = Counter(k for k, _ in src_keys)
        have = Counter(k for k, _ in tgt_keys)
        reported: set[str] = set()
        for key, offset in src_keys:
            if want[key] > have[key] and key not in reported:
                reported.add(key)
                line, col = line_col(source, offset)
                findings.append(
                    PairFinding(
                        rule="number",
                        severity="error",
                        side="source",
                        line=line,
                        column=col,
                        text=key,
                        message=f"'{key}' is in the source {want[key]} time(s) and in the "
                        f"target {have[key]}",
                    )
                )
        for key, offset in tgt_keys:
            if have[key] > want[key] and key not in reported:
                reported.add(key)
                line, col = line_col(target, offset)
                findings.append(
                    PairFinding(
                        rule="number",
                        severity="error",
                        side="target",
                        line=line,
                        column=col,
                        text=key,
                        message=f"'{key}' is in the target {have[key]} time(s) and in the "
                        f"source {want[key]}",
                    )
                )

    def _names_rule(
        self, source: str, masked_source: str, folded_masked: str, findings: list[PairFinding]
    ) -> None:
        # Counted outside code and URLs: a link that contains the name is not a use of it.
        for name, in_source, in_target in self._names:
            hits = list(in_source.finditer(masked_source))
            have = len(in_target.findall(folded_masked))
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

    def _address(self, target: str, masked_target: str, findings: list[PairFinding]) -> None:
        if self.market.address is None:
            return
        wrong = _NL_FORMAL if self.market.address == "informal" else _NL_INFORMAL
        for n, m in enumerate(wrong.finditer(masked_target)):
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


def _folded_offset(index: list[int], original: int) -> int:
    """The folded offset of an original offset (the index is sorted)."""
    return bisect_left(index, original)


class _Open:
    """Source quantities that found no match, looked up without scanning all of them: by value
    (the kind changed), by a thousand times the value (read in the other format), and by
    paragraph (the only unmatched number there was probably replaced)."""

    def __init__(self, src: list[Quantity], left: list[int], para_of: list[int]):
        self._src = src
        self._para_of = para_of
        self._left = dict.fromkeys(left)
        self._by_value: dict[Decimal, list[int]] = defaultdict(list)
        self._by_para: dict[int, list[int]] = defaultdict(list)
        for i in left:
            self._by_value[src[i].value].append(i)
            if para_of:
                self._by_para[para_of[src[i].start]].append(i)

    def _first(self, candidates: list[int]) -> int | None:
        return next((i for i in candidates if i in self._left), None)

    def take(self, t: Quantity, paragraph: int | None) -> int | None:
        found = self._first(self._by_value.get(t.value, []))
        if found is None:
            for value in (t.value * 1000, t.value / Decimal(1000)):
                found = self._first(self._by_value.get(value, []))
                if found is not None:
                    break
        if found is None and paragraph is not None:
            same = [i for i in self._by_para.get(paragraph, []) if i in self._left]
            if len(same) == 1:
                found = same[0]
        if found is not None:
            del self._left[found]
        return found

    def remaining(self) -> list[int]:
        return list(self._left)
