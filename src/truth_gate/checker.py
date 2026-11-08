"""The four checks. Errors fail a document; warnings never do.

1. number  - every quantity must equal a quantity in some fact AND the words around it must
             share at least `min_context_overlap` content words with that fact's text.
2. skill   - every recognised skill/tool term must be allowed by the facts file.
3. blocked - a blocked phrase anywhere fails the document.
4. tone    - machine-tone phrases are reported as warnings.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from truth_gate.facts import Fact, Facts
from truth_gate.numbers import Quantity, find_quantities, same_quantity
from truth_gate.report import Finding, Report, Trace
from truth_gate.skills import Vocabulary, builtin_tone, phrase_pattern
from truth_gate.text import Span, content_words, line_col, mask, sentence_spans, stem

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


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
        text = mask(document)
        findings: list[Finding] = []
        traces: list[Trace] = []
        sentences = sentence_spans(text)
        quantities = find_quantities(text)
        for q in quantities:
            self._check_number(
                document, text, q, _sentence_of(sentences, q.start), findings, traces
            )
        hits = self.vocabulary.find(text)
        for h in hits:
            if h.canonical not in self.vocabulary.allowed:
                line, col = line_col(document, h.start)
                findings.append(
                    Finding(
                        check="skill",
                        severity="error",
                        line=line,
                        column=col,
                        text=h.text,
                        message=(
                            f"'{h.text}'"
                            + (f" ({h.canonical})" if h.canonical != h.text else "")
                            + " is not a skill in the facts file"
                        ),
                    )
                )
        for phrase, rx in self._blocked:
            for m in rx.finditer(text):
                line, col = line_col(document, m.start())
                findings.append(
                    Finding(
                        check="blocked",
                        severity="error",
                        line=line,
                        column=col,
                        text=m.group(0),
                        message=f"blocked phrase '{phrase}'",
                    )
                )
        for phrase, rx in self._tone:
            for m in rx.finditer(text):
                line, col = line_col(document, m.start())
                findings.append(
                    Finding(
                        check="tone",
                        severity="warning",
                        line=line,
                        column=col,
                        text=m.group(0),
                        message=f"machine-tone phrase '{phrase}'",
                    )
                )
        findings.sort(key=lambda f: (f.line, f.column, f.check))
        errors = sum(f.severity == "error" for f in findings)
        return Report(
            passed=errors == 0,
            errors=errors,
            warnings=len(findings) - errors,
            numbers_checked=len(quantities),
            skills_checked=len(hits),
            findings=findings,
            traces=traces,
        )

    def _check_number(
        self,
        document: str,
        text: str,
        q: Quantity,
        sentence: Span,
        findings: list[Finding],
        traces: list[Trace],
    ) -> None:
        line, col = line_col(document, q.start)
        candidates = [
            f for f in self.facts.facts if any(same_quantity(q, fq) for fq in self._fact_qty[f.id])
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
            return
        window = self._window(text, sentence, q)
        best: tuple[int, Fact, set[str]] | None = None
        for f in candidates:
            shared = window & self._fact_words[f.id]
            if best is None or len(shared) > best[0]:
                best = (len(shared), f, shared)
        assert best is not None  # noqa: S101 - candidates is non-empty
        if best[0] >= self.facts.min_context_overlap:
            traces.append(
                Trace(line=line, text=q.text, fact_id=best[1].id, shared_words=sorted(best[2]))
            )
            return
        findings.append(
            Finding(
                check="number",
                severity="error",
                line=line,
                column=col,
                text=q.text,
                message=(
                    f"{q.label()} appears in a fact, but the words around it share no topic with "
                    "that fact (number used out of context)"
                ),
                fact_ids=[f.id for f in candidates],
            )
        )

    def _window(self, text: str, sentence: Span, q: Quantity) -> set[str]:
        """Content words within `context_window` words either side of q, inside its sentence."""
        n = self.facts.context_window
        words = [m for m in _WORD.finditer(text, sentence.start, sentence.end)]
        before = [m.group(0) for m in words if m.end() <= q.start][-n:]
        after = [m.group(0) for m in words if m.start() >= q.end][:n]
        return content_words(" ".join(before + after)) - self._ignore


def _sentence_of(sentences: Sequence[Span], offset: int) -> Span:
    for s in sentences:
        if s.start <= offset < s.end:
            return s
    return Span(max(0, offset - 200), offset + 200)


__all__ = ["Checker", "stem"]
