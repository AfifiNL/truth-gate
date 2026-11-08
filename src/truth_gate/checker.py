"""The four checks. Errors fail a document; warnings never do.

1. number  - every quantity must equal a quantity in some fact AND the words around it, in the
             same sentence or line, must share at least `min_context_overlap` content words
             with that fact's text. Code, comments, URLs and list markers are masked first
             (numbers there are not claims); see `text.mask` and `numbers.SKIP_RULES`.
2. skill   - every recognised skill/tool term must be allowed by the facts file.
3. blocked - a blocked phrase anywhere fails the document.
4. tone    - machine-tone phrases are reported as warnings.

Skills, blocked phrases and tone are checked on the original text, code spans included:
masking exists only so that numbers in code or links are not read as claims.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right

from truth_gate.facts import Facts
from truth_gate.numbers import Quantity, same_quantity, scan
from truth_gate.report import Finding, Report, Trace
from truth_gate.skills import Vocabulary, builtin_tone, phrase_pattern
from truth_gate.text import Span, content_words, line_col, mask, sentence_spans, span_at

MAX_DOCUMENT_CHARS = 200_000
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_CLAUSE_BREAK = re.compile(r"[,;:](?=\s)|[()]|\s[-\u2013\u2014]\s")
_FIRST_WORD = re.compile(r"[\s\-*+#>|]*(?:\d{1,9}[.)]\s+)?")


class DocumentTooLarge(ValueError):
    """The document is longer than MAX_DOCUMENT_CHARS."""


class Checker:
    def __init__(self, facts: Facts):
        self.facts = facts
        self.vocabulary = Vocabulary(facts)
        # The subject's own name appears everywhere; it is not evidence of a shared context.
        self._ignore = content_words(facts.subject)
        self._fact_words = {f.id: content_words(f.text) - self._ignore for f in facts.facts}
        self._fact_qty = {f.id: f.quantities() for f in facts.facts}
        self._blocked = [(p, phrase_pattern(p)) for p in facts.blocked_phrases if p.strip()]
        tone = facts.tone_phrases if facts.tone_phrases is not None else builtin_tone()
        self._tone = [(p, phrase_pattern(p)) for p in tone if p.strip()]

    def check(self, document: str) -> Report:
        if len(document) > MAX_DOCUMENT_CHARS:
            raise DocumentTooLarge(
                f"document has {len(document):,} characters; the limit is {MAX_DOCUMENT_CHARS:,}"
            )
        findings: list[Finding] = []
        traces: list[Trace] = []
        n_numbers = self._numbers(document, findings, traces)
        n_skills = self._skills(document, findings)
        for check, phrases in (("blocked", self._blocked), ("tone", self._tone)):
            for phrase, rx in phrases:
                for m in rx.finditer(document):
                    line, col = line_col(document, m.start())
                    findings.append(
                        Finding(
                            check="blocked" if check == "blocked" else "tone",
                            severity="error" if check == "blocked" else "warning",
                            line=line,
                            column=col,
                            text=m.group(0),
                            message=(
                                f"blocked phrase '{phrase}'"
                                if check == "blocked"
                                else f"machine-tone phrase '{phrase}'"
                            ),
                        )
                    )
        findings.sort(key=lambda f: (f.line, f.column, f.check))
        errors = sum(f.severity == "error" for f in findings)
        return Report(
            passed=errors == 0,
            errors=errors,
            warnings=len(findings) - errors,
            numbers_checked=n_numbers,
            skills_checked=n_skills,
            findings=findings,
            traces=traces,
        )

    # -- numbers ---------------------------------------------------------------------------

    def _numbers(self, document: str, findings: list[Finding], traces: list[Trace]) -> int:
        text = mask(document)
        sentences = sentence_spans(text)
        starts = [s.start for s in sentences]
        words = list(_WORD.finditer(text))
        word_starts = [w.start() for w in words]
        quantities, _skipped = scan(text)
        found = list(_CLAUSE_BREAK.finditer(text))
        breaks = ([m.start() for m in found], [m.end() for m in found])
        for q in quantities:
            line, col = line_col(document, q.start)
            sentence = span_at(sentences, starts, q.start) or Span(q.start, q.end)
            candidates = [
                f
                for f in self.facts.facts
                if any(same_quantity(q, fq) for fq in self._fact_qty[f.id])
            ]
            if not candidates:
                findings.append(
                    Finding(
                        check="number",
                        severity="error",
                        line=line,
                        column=col,
                        text=q.text,
                        message=f"{q.label()} does not appear in any fact",
                    )
                )
                continue
            window = self._window(words, word_starts, sentence, q)
            best_id: str = ""
            best_shared: set[str] = set()
            for f in candidates:
                shared = window & self._fact_words[f.id]
                if not best_id or len(shared) > len(best_shared):
                    best_id, best_shared = f.id, shared
            # Misplaced number: the words around it match another fact (one that does not
            # contain this number) clearly better than any fact that does. "26 hours to 9 hours"
            # shares "support" with the 9-person team fact, but five words with the
            # response-time fact.
            # The comparison uses the number's clause (bounded by , ; : brackets or a spaced
            # dash), because one sentence often joins two facts: "Holding a BA ... in 2014,
            # Jordan wrote 60 help-centre articles ..." must not move 2014 to the articles.
            clause = self._clause_words(breaks, words, word_starts, sentence, q)
            own = max(len(clause & self._fact_words[f.id]) for f in candidates)
            other_id = ""
            other_shared: set[str] = set()
            for f in self.facts.facts:
                if f in candidates:
                    continue
                shared = clause & self._fact_words[f.id]
                if len(shared) > len(other_shared):
                    other_id, other_shared = f.id, shared
            margin = self.facts.misplaced_margin
            if margin and len(other_shared) >= own + margin:
                findings.append(
                    Finding(
                        check="number",
                        severity="error",
                        line=line,
                        column=col,
                        text=q.text,
                        message=(
                            f"{q.label()} comes from fact '{best_id}', but the words around it "
                            f"match fact '{other_id}' ({', '.join(sorted(other_shared))}) "
                            "better: the number looks moved from another claim"
                        ),
                        fact_ids=[f.id for f in candidates],
                    )
                )
                continue
            if len(best_shared) >= self.facts.min_context_overlap:
                traces.append(
                    Trace(line=line, text=q.text, fact_id=best_id, shared_words=sorted(best_shared))
                )
                continue
            findings.append(
                Finding(
                    check="number",
                    severity="error",
                    line=line,
                    column=col,
                    text=q.text,
                    message=(
                        f"{q.label()} appears in a fact, but the words around it share no topic "
                        "with that fact (number used out of context)"
                    ),
                    fact_ids=[f.id for f in candidates],
                )
            )
        return len(quantities)

    def _clause_words(
        self,
        breaks: tuple[list[int], list[int]],
        words: list[re.Match[str]],
        word_starts: list[int],
        sentence: Span,
        q: Quantity,
    ) -> set[str]:
        """Content words of the clause around q (within its sentence and window).

        `breaks` holds the start and end offsets of every clause break in the text, found once
        per document, so each lookup is a binary search.
        """
        starts, ends = breaks
        i = bisect_right(ends, q.start) - 1
        start = max(sentence.start, ends[i]) if i >= 0 else sentence.start
        j = bisect_left(starts, q.end)
        end = min(sentence.end, starts[j]) if j < len(starts) else sentence.end
        return self._window(words, word_starts, Span(start, end), q)

    def _window(
        self, words: list[re.Match[str]], word_starts: list[int], sentence: Span, q: Quantity
    ) -> set[str]:
        """Content words within `context_window` words either side of q, inside its sentence."""
        n = self.facts.context_window
        lo = bisect_left(word_starts, sentence.start)
        hi = bisect_left(word_starts, sentence.end)
        mid = bisect_left(word_starts, q.start, lo, hi)
        before = [w.group(0) for w in words[max(lo, mid - n) : mid] if w.end() <= q.start]
        after_start = bisect_left(word_starts, q.end, lo, hi)
        after = [w.group(0) for w in words[after_start : min(hi, after_start + n)]]
        return content_words(" ".join(before + after)) - self._ignore

    # -- skills ----------------------------------------------------------------------------

    def _skills(self, document: str, findings: list[Finding]) -> int:
        hits = self.vocabulary.find(document)
        firsts = {_first_word(document, s) for s in sentence_spans(document)}
        for h in hits:
            if h.canonical in self.vocabulary.allowed:
                continue
            line, col = line_col(document, h.start)
            name = f"'{h.text}'" + (f" ({h.canonical})" if h.canonical != h.text else "")
            if h.ambiguous and h.start in firsts:
                # "Swift responses", "Spark joy": a capitalised English word opening a sentence.
                findings.append(
                    Finding(
                        check="skill",
                        severity="warning",
                        line=line,
                        column=col,
                        text=h.text,
                        message=f"{name} opens a sentence: check it is not a skill claim",
                    )
                )
                continue
            findings.append(
                Finding(
                    check="skill",
                    severity="error",
                    line=line,
                    column=col,
                    text=h.text,
                    message=f"{name} is not a skill in the facts file",
                )
            )
        return len(hits)


def _first_word(text: str, sentence: Span) -> int:
    """Offset of a sentence's first word, after bullets, heading marks and list numbers."""
    m = _FIRST_WORD.match(text, sentence.start)
    return m.end() if m else sentence.start
