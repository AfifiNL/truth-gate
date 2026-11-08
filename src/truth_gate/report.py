"""Findings and the report a check returns (JSON-serialisable via pydantic)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Check = Literal["number", "skill", "blocked", "tone"]
Severity = Literal["error", "warning"]


class Finding(BaseModel):
    check: Check
    severity: Severity
    line: int
    column: int
    text: str = Field(description="The matched text in the document.")
    message: str
    fact_ids: list[str] = Field(default_factory=list, description="Facts considered, if any.")


class Trace(BaseModel):
    """A number that passed, and the fact that supports it."""

    line: int
    text: str
    fact_id: str
    shared_words: list[str]


class Report(BaseModel):
    passed: bool
    errors: int
    warnings: int
    numbers_checked: int
    skills_checked: int
    findings: list[Finding]
    traces: list[Trace]

    def render(self) -> str:
        lines = [
            f"{'PASS' if self.passed else 'FAIL'}: {self.errors} error(s), {self.warnings} "
            f"warning(s); {self.numbers_checked} number(s) and {self.skills_checked} skill "
            "mention(s) checked",
        ]
        for f in self.findings:
            ids = f" [facts: {', '.join(f.fact_ids)}]" if f.fact_ids else ""
            lines.append(
                f"  {f.severity.upper():7} {f.line}:{f.column} {f.check}: {f.message}{ids}"
            )
        if self.traces:
            lines.append("  traced numbers:")
            for t in self.traces:
                lines.append(f"    {t.line}: {t.text} <- {t.fact_id} ({', '.join(t.shared_words)})")
        return "\n".join(lines)
