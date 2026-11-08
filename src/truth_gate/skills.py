"""Recognise skill and tool terms in text and map them to one canonical name."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources

from truth_gate.facts import Facts


@dataclass(frozen=True)
class Term:
    canonical: str
    surface: str
    case_sensitive: bool

    @property
    def ambiguous(self) -> bool:
        """A case-sensitive, title-case word that is also an English word ("Swift", "Spark")."""
        return self.case_sensitive and self.surface[:1].isupper() and self.surface[1:].islower()


@dataclass(frozen=True)
class TermHit:
    canonical: str
    start: int
    end: int
    text: str
    ambiguous: bool = False


def _read_data(name: str) -> list[str]:
    raw = resources.files("truth_gate").joinpath("data", name).read_text(encoding="utf-8")
    return [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def builtin_terms() -> list[Term]:
    terms: list[Term] = []
    for line in _read_data("skills.txt"):
        parts = [p.strip() for p in line.split("|")]
        canonical = parts[0].lstrip("=")
        for p in parts:
            terms.append(Term(canonical, p.lstrip("="), p.startswith("=")))
    return terms


def builtin_tone() -> list[str]:
    return _read_data("tone.txt")


def _pattern(term: Term) -> re.Pattern[str]:
    # Word-ish boundaries that also work for "C++", "C#", ".NET" and "Node.js". An ambiguous
    # word followed by "-to" ("Go-to-market") is the English word, not the tool.
    body = re.escape(term.surface).replace(r"\ ", r"\s+")
    tail = r"(?![\w+#&]|\.\w)" + (r"(?!-to\b)" if term.ambiguous else "")
    return re.compile(r"(?<![\w+#&])" + body + tail, 0 if term.case_sensitive else re.I)


class Vocabulary:
    """All recognised terms: built-in list + the facts file's skills and extra vocabulary."""

    def __init__(self, facts: Facts):
        terms = builtin_terms()
        by_surface = {t.surface.lower(): t.canonical for t in terms}
        # Facts-file skills: a name or alias that is already known maps to that canonical name,
        # so "Postgres" in the facts file allows "PostgreSQL" in the document.
        self.allowed: set[str] = set()
        for skill in facts.skills:
            canonical = next(
                (
                    by_surface[s.lower()]
                    for s in [skill.name, *skill.aliases]
                    if s.lower() in by_surface
                ),
                skill.name,
            )
            self.allowed.add(canonical)
            for s in [skill.name, *skill.aliases]:
                terms.append(Term(canonical, s, False))
        for extra in facts.vocabulary:
            terms.append(Term(by_surface.get(extra.lower(), extra), extra, False))
        # Longest surface first, so "Google Cloud Platform" wins over "Google Cloud".
        uniq = {(t.surface, t.case_sensitive): t for t in terms}
        self.terms = sorted(uniq.values(), key=lambda t: len(t.surface), reverse=True)
        self._patterns = [(t, _pattern(t)) for t in self.terms]
        # Terms named in the facts' own text are true statements, so they are allowed too.
        for fact in facts.facts:
            for hit in self.find(fact.text):
                self.allowed.add(hit.canonical)

    def find(self, text: str) -> list[TermHit]:
        hits: list[TermHit] = []
        taken = [False] * len(text)
        for term, rx in self._patterns:
            for m in rx.finditer(text):
                if any(taken[m.start() : m.end()]):
                    continue
                for i in range(m.start(), m.end()):
                    taken[i] = True
                hits.append(TermHit(term.canonical, m.start(), m.end(), m.group(0), term.ambiguous))
        hits.sort(key=lambda h: h.start)
        return hits


def phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Case-insensitive whole-phrase match; any run of whitespace matches a space."""
    body = re.escape(phrase.strip()).replace(r"\ ", r"\s+")
    return re.compile(r"(?<!\w)" + body + r"(?!\w)", re.I)
