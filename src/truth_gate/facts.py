"""The facts file: the only source a checked document may draw numbers and skills from."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from truth_gate.numbers import ISO_CODES, Kind, Quantity, find_quantities


class FactsError(ValueError):
    """The facts file is missing, unreadable or invalid."""


class ExtraNumber(BaseModel):
    """A number a fact supports that its text does not spell out (e.g. a derived total)."""

    model_config = ConfigDict(extra="forbid")
    value: Decimal
    unit: str = Field(default="plain", description="plain, percent, or an ISO currency code")

    @field_validator("unit")
    @classmethod
    def _known_unit(cls, v: str) -> str:
        if v not in ("plain", "percent") and v not in ISO_CODES:
            raise ValueError(f"unit must be plain, percent or an ISO currency code, not {v!r}")
        return v


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
    min_context_overlap: StrictInt = Field(default=1, ge=1)
    context_window: StrictInt = Field(default=8, ge=1)
    misplaced_margin: StrictInt = Field(
        default=2,
        ge=0,
        description="Flag a number when a fact without it shares this many more context words "
        "than the best fact with it (0 switches the rule off).",
    )

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


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys: a second `blocked_phrases: []` must not
    silently switch a check off."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_facts(path: str | Path) -> Facts:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        raw = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - a SafeLoader subclass
    except OSError as exc:
        raise FactsError(f"cannot read facts file {p}: {exc.strerror}") from None
    except UnicodeDecodeError:
        raise FactsError(f"facts file {p} is not valid UTF-8") from None
    except yaml.YAMLError as exc:
        raise FactsError(f"facts file {p} is not valid YAML: {exc}") from None
    except (TypeError, RecursionError) as exc:  # an unhashable key, or nesting too deep
        raise FactsError(f"facts file {p} is not valid YAML: {type(exc).__name__}") from None
    return parse_facts(raw, str(p))


def parse_facts(raw: object, where: str = "facts") -> Facts:
    if not isinstance(raw, dict):
        raise FactsError(f"{where}: expected a mapping at the top level")
    try:
        return Facts.model_validate(raw)
    except ValueError as exc:
        raise FactsError(f"{where}: {exc}") from None
