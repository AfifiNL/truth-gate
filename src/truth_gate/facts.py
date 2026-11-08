"""The facts file: the only source a checked document may draw numbers and skills from."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from truth_gate.numbers import Kind, Quantity, find_quantities


class FactsError(ValueError):
    """The facts file is missing, unreadable or invalid."""


class ExtraNumber(BaseModel):
    """A number a fact supports that its text does not spell out (e.g. a derived total)."""

    model_config = ConfigDict(extra="forbid")
    value: Decimal
    unit: Literal["plain", "percent", "EUR", "USD", "GBP"] = "plain"


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source: str = Field(min_length=1, description="Where a reviewer can check this fact.")
    numbers: list[ExtraNumber] = Field(default_factory=list)

    def quantities(self) -> list[Quantity]:
        qs = find_quantities(self.text)
        for n in self.numbers:
            kind: Kind = (
                "plain" if n.unit == "plain" else "percent" if n.unit == "percent" else "money"
            )
            currency = n.unit if kind == "money" else None
            qs.append(Quantity(n.value, kind, currency, -1, -1, f"{n.value} {n.unit}"))
        return qs


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)


class Facts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, description="Who or what the facts are about.")
    facts: list[Fact] = Field(min_length=1)
    skills: list[Skill] = Field(default_factory=list)
    vocabulary: list[str] = Field(
        default_factory=list, description="Extra skill/tool terms to recognise in documents."
    )
    blocked_phrases: list[str] = Field(default_factory=list)
    tone_phrases: list[str] | None = Field(
        default=None, description="Replaces the built-in tone list when given."
    )
    min_context_overlap: int = Field(default=1, ge=1)
    context_window: int = Field(default=8, ge=1)

    @field_validator("skills", mode="before")
    @classmethod
    def _skills_as_names(cls, v: object) -> object:
        # Allow plain strings in YAML: `skills: [Python, PostgreSQL]`.
        if isinstance(v, list):
            return [{"name": s} if isinstance(s, str) else s for s in v]
        return v

    @model_validator(mode="after")
    def _unique_ids(self) -> Facts:
        seen: set[str] = set()
        for f in self.facts:
            if f.id in seen:
                raise ValueError(f"duplicate fact id: {f.id}")
            seen.add(f.id)
        return self


def load_facts(path: str | Path) -> Facts:
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FactsError(f"cannot read facts file {p}: {exc.strerror}") from None
    except yaml.YAMLError as exc:
        raise FactsError(f"facts file {p} is not valid YAML: {exc}") from None
    return parse_facts(raw, str(p))


def parse_facts(raw: object, where: str = "facts") -> Facts:
    if not isinstance(raw, dict):
        raise FactsError(f"{where}: expected a mapping at the top level")
    try:
        return Facts.model_validate(raw)
    except ValueError as exc:
        raise FactsError(f"{where}: {exc}") from None
