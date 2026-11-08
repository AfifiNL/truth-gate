"""Text helpers: masking of non-prose spans (for the number check), sentences, content words.

Masking replaces characters with spaces instead of deleting them, so every offset found later
still points at the same line and column of the original document. Every pattern here runs in
linear time; unclosed fences and comments are left unmasked (their numbers are checked).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

_FENCE_OPEN = re.compile(r"[ ]{0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_LINK_TARGET = re.compile(r"\]\([^()\s\]]*\)")
_URL = re.compile(r"\bhttps?://\S+|\bwww\.\S+")
_ORDERED = re.compile(r"[ \t]*(\d{1,9})[.)](?=[ \t])")
_BULLET = re.compile(r"[ \t]*[-*+](?=[ \t])")


def _lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    pos = 0
    for line in text.split("\n"):
        out.append((pos, line))
        pos += len(line) + 1
    return out


def mask(text: str) -> str:
    """Blank out spans that carry no number claims, keeping every offset unchanged.

    Masked: fenced code blocks (``` and ~~~), HTML comments, inline code, link targets, URLs,
    and ordered-list markers. A line starting "40. " is a list marker only where a Markdown
    list can start (after a blank line, inside a list, or when the number is 1); otherwise it is
    a wrapped sentence and its number is checked.
    """
    chars = list(text)

    def blank(a: int, b: int) -> None:
        for i in range(a, b):
            if chars[i] != "\n":
                chars[i] = " "

    lines = _lines(text)
    # 1. Fenced code: one pass. An unclosed fence stops fence handling: the rest stays prose.
    i = 0
    while i < len(lines):
        m = _FENCE_OPEN.match(lines[i][1])
        if not m:
            i += 1
            continue
        fence = m.group(1)
        closer = re.compile(r"[ ]{0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*$")
        j = next((k for k in range(i + 1, len(lines)) if closer.match(lines[k][1])), None)
        if j is None:
            break
        blank(lines[i][0], lines[j][0] + len(lines[j][1]))
        i = j + 1
    # 2. HTML comments, found with str.find (linear); an unclosed comment is not masked.
    work = "".join(chars)
    pos = 0
    while (a := work.find("<!--", pos)) != -1:
        b = work.find("-->", a + 4)
        if b == -1:
            break
        blank(a, b + 3)
        pos = b + 3
    # 3. Inline code, link targets, URLs.
    work = "".join(chars)
    for rx in (_INLINE_CODE, _LINK_TARGET, _URL):
        for m in rx.finditer(work):
            blank(m.start(), m.end())
    # 4. Ordered-list markers (CommonMark: a list starts after a blank line, continues inside a
    #    list, and may interrupt a paragraph only when it starts at 1).
    prev_blank, in_list = True, False
    for start, line in lines:
        if not line.strip():
            prev_blank = True
            continue
        if m := _ORDERED.match(line):
            if prev_blank or in_list or int(m.group(1)) == 1:
                blank(start + m.start(1), start + m.end())
                in_list = True
            else:
                in_list = False
        elif _BULLET.match(line):
            in_list = True
        elif not (in_list and line[:1] in (" ", "\t")):
            in_list = False
        prev_blank = False
    return "".join(chars)


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


_BOUNDARY = re.compile(r"\n|(?<=[.!?])[ \t]+(?=[A-Z0-9\"'(\[])")


def sentence_spans(text: str) -> list[Span]:
    """Sentence boundaries: sentence-ending punctuation before a capital or digit, and EVERY
    line break (list items, headings and wrapped lines never share context across lines).

    A full stop inside a number ("1.5") is not followed by whitespace, so it never splits.
    """
    spans: list[Span] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        if m.start() > start:
            spans.append(Span(start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append(Span(start, len(text)))
    return spans


def span_at(spans: list[Span], starts: list[int], offset: int) -> Span | None:
    """The span containing `offset` (spans sorted, `starts` their start offsets)."""
    i = bisect_right(starts, offset) - 1
    if i >= 0 and spans[i].start <= offset < spans[i].end:
        return spans[i]
    return None


def line_col(text: str, offset: int) -> tuple[int, int]:
    """1-based line and column of a character offset."""
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, col
