"""Text helpers: masking of non-prose spans, sentences, content words.

Masking replaces characters with spaces instead of deleting them, so every offset found later
still points at the same line and column of the original document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Spans that are not prose claims: fenced code, inline code, URLs, link targets, HTML comments,
# and ordered-list markers ("1. ", "2) ") at the start of a line.
_MASKS = [
    re.compile(r"```.*?```", re.S),
    re.compile(r"~~~.*?~~~", re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"\]\([^)\s]*\)"),
    re.compile(r"\bhttps?://\S+|\bwww\.\S+"),
    re.compile(r"(?m)^[ \t]*\d{1,3}[.)](?=[ \t])"),
]


def mask(text: str) -> str:
    """Blank out spans that carry no claims, keeping every offset unchanged."""
    out = text
    for rx in _MASKS:
        out = rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), out)
    return out


STOPWORDS = frozenset(
    """a about above after again against all also am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for from
    further had has have having he her here hers herself him himself his how i if in into is it
    its itself just me more most my myself no nor not now of off on once only or other our ours
    ourselves out over own per same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up very via was we
    were what when where which while who whom why will with would you your yours yourself
    yourselves within across around among including total overall approximately about nearly
    almost roughly more than less over under up to""".split()
    + """year years month months week weeks day days time times number percent per cent""".split()
)
# Generic unit-like words are stopwords on purpose: "12 years" and "12 months" must share a
# topic word ("engineers", "budget"), not just the unit, to count as the same context.

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


def stem(word: str) -> str:
    """A deliberately small stemmer: plural and a few verb endings, so that "conferences" and
    "conference", or "migrated" and "migration", compare equal. Not a linguistic stemmer."""
    w = word.lower().strip("'-")
    if w.endswith("'s"):
        w = w[:-2]
    if len(w) <= 4:
        return w
    if w.endswith("ies"):
        w = w[:-3] + "y"
    elif w.endswith(("sses", "ches", "shes", "xes", "zes")):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for suffix, repl in (("ement", ""), ("ation", "at"), ("ing", ""), ("ed", "")):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)] + repl
    return w


def content_words(text: str) -> set[str]:
    """Stemmed content words: no stopwords, no numbers, at least three letters."""
    return {
        stem(m.group(0))
        for m in _WORD.finditer(text)
        if len(m.group(0)) >= 3 and m.group(0).lower() not in STOPWORDS
    }


@dataclass(frozen=True)
class Span:
    start: int
    end: int


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n\s*\n|\n(?=\s*[-*+#>|])")


def sentence_spans(text: str) -> list[Span]:
    """Rough sentence boundaries; bullet lines, headings and paragraphs end a sentence too.

    A full stop inside a number ("1.5") is not followed by whitespace, so it never splits.
    """
    spans: list[Span] = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        if m.start() > start:
            spans.append(Span(start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append(Span(start, len(text)))
    return spans


def line_col(text: str, offset: int) -> tuple[int, int]:
    """1-based line and column of a character offset."""
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, col
