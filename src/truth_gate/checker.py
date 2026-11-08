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
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from truth_gate.facts import Facts
from truth_gate.numbers import Quantity, same_quantity, scan
from truth_gate.report import Finding, Report, Trace
from truth_gate.skills import Vocabulary, builtin_tone, phrase_pattern
from truth_gate.text import Span, content_words, line_col, mask, sentence_spans, span_at

MAX_DOCUMENT_CHARS = 200_000
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_CLAUSE_BREAK = re.compile(
    r"[,;:](?=\s)|[()]|\s[-\u2013\u2014]\s|\s(?:and|but|while|whereas)\s", re.I
)
_FIRST_WORD = re.compile(r"[\s\-*+#>|]*(?:\d{1,9}[.)]\s+)?")


@dataclass(frozen=True)
class _Decision:
    best_id: str
    best_words: list[str]
    moved_from: str
    moved_words: tuple[str, ...]


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
        self._order = {f.id: i for i, f in enumerate(facts.facts)}
        # Indexes so the cost per number does not grow with every fact: value -> facts holding
        # that value, word -> facts containing that word.
        self._by_value: dict[Decimal, list[tuple[str, Quantity]]] = defaultdict(list)
        for f in facts.facts:
            for fq in self._fact_qty[f.id]:
                self._by_value[fq.value].append((f.id, fq))
        self._by_word: dict[str, list[str]] = defaultdict(list)
        for f in facts.facts:
            for w in self._fact_words[f.id]:
                self._by_word[w].append(f.id)
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
        cache: dict[tuple[frozenset[str], frozenset[str], tuple[str, ...]], _Decision] = {}
        for q in quantities:
            line, col = line_col(document, q.start)
            sentence = span_at(sentences, starts, q.start) or Span(q.start, q.end)
            candidates = tuple(
                sorted(
                    {fid for fid, fq in self._by_value.get(q.value, ()) if same_quantity(q, fq)},
                    key=self._order.__getitem__,
                )
            )
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
            # Only words that occur in some fact can change the decision, so the cache key
            # keeps just those: repeated or near-repeated text costs one computation.
            window = frozenset(
                w for w in self._window(words, word_starts, sentence, q) if w in self._by_word
            )
            clause = frozenset(
                w
                for w in self._clause_words(breaks, words, word_starts, sentence, q)
                if w in self._by_word
            )
            key = (window, clause, candidates)
            if key not in cache:
                cache[key] = self._decide(window, clause, candidates)
            d = cache[key]
            if d.moved_from:
                findings.append(
                    Finding(
                        check="number",
                        severity="error",
                        line=line,
                        column=col,
                        text=q.text,
                        message=(
                            f"{q.label()} comes from fact '{d.best_id}', but the words around it "
                            f"match fact '{d.moved_from}' ({', '.join(d.moved_words)}) better: "
                            "the number looks moved from another claim"
                        ),
                        fact_ids=list(candidates),
                    )
                )
            elif len(d.best_words) >= self.facts.min_context_overlap:
                traces.append(
                    Trace(line=line, text=q.text, fact_id=d.best_id, shared_words=d.best_words)
                )
            else:
                findings.append(
                    Finding(
                        check="number",
                        severity="error",
                        line=line,
                        column=col,
                        text=q.text,
                        message=(
                            f"{q.label()} appears in a fact, but the words around it share no "
                            "topic with that fact (number used out of context)"
                        ),
                        fact_ids=list(candidates),
                    )
                )
        return len(quantities)

    def _decide(
        self, window: frozenset[str], clause: frozenset[str], candidates: tuple[str, ...]
    ) -> _Decision:
        """Which fact supports a number, and whether it looks moved from another fact.

        best: the candidate fact (one holding this number) sharing most window words.
        moved: a fact WITHOUT this number matches the number's clause by `misplaced_margin`
        or more words than any candidate does ("26 hours to 9 hours" shares "support" with a
        fact about a team of 9, but four words with the response-time fact). The clause, not
        the sentence, because one sentence often joins two facts ("Holding a BA ... in 2014,
        Jordan wrote 60 articles ...", "Automated 35% of routing and wrote 60 articles").
        """
        best_id, best = candidates[0], window & self._fact_words[candidates[0]]
        for fid in candidates[1:]:
            shared = window & self._fact_words[fid]
            if len(shared) > len(best):
                best_id, best = fid, shared
        margin = self.facts.misplaced_margin
        moved_from: str = ""
        moved_words: tuple[str, ...] = ()
        if margin and clause:
            own = max(len(clause & self._fact_words[fid]) for fid in candidates)
            counts: dict[str, int] = defaultdict(int)
            for w in clause:
                for fid in self._by_word[w]:
                    counts[fid] += 1
            cand = set(candidates)
            others = [(n, -self._order[fid], fid) for fid, n in counts.items() if fid not in cand]
            if others:
                n, _, fid = max(others)
                if n >= own + margin:
                    moved_from = fid
                    moved_words = tuple(sorted(clause & self._fact_words[fid]))
        return _Decision(best_id, sorted(best), moved_from, moved_words)

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
