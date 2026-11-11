"""The brand file: per market, the rules a localised draft must follow."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from truth_gate.facts import _UniqueKeyLoader
from truth_gate.locales import SUPPORTED, language_of


class BrandError(ValueError):
    """The brand file is missing, unreadable or invalid, or a market is not in it."""


def _no_blanks(values: list[str], what: str) -> list[str]:
    if any(not v.strip() for v in values):
        raise ValueError(f"{what} must not contain an empty entry")
    return values


class Term(BaseModel):
    """When the source uses `source`, the target must use one of the `target` forms."""

    model_config = ConfigDict(extra="forbid")
    source: list[str] = Field(min_length=1)
    target: list[str] = Field(min_length=1)

    @field_validator("source", mode="before")
    @classmethod
    def _one_or_many(cls, v: object) -> object:
        return [v] if isinstance(v, str) else v

    @field_validator("source", "target")
    @classmethod
    def _filled(cls, v: list[str]) -> list[str]:
        return _no_blanks(v, "a term")


class Market(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: Literal["formal", "informal"] | None = Field(
        default=None, description="Dutch only: informal fails on u/uw, formal on je/jij/jouw."
    )
    terms: list[Term] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    required_lines: list[str] = Field(default_factory=list)

    @field_validator("forbidden", "required_lines")
    @classmethod
    def _filled(cls, v: list[str]) -> list[str]:
        return _no_blanks(v, "forbidden and required_lines")


class Brand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str = Field(min_length=1)
    source_locale: Literal["en"] = "en"
    do_not_translate: list[str] = Field(default_factory=list)
    markets: dict[str, Market] = Field(min_length=1)

    @field_validator("do_not_translate")
    @classmethod
    def _filled(cls, v: list[str]) -> list[str]:
        return _no_blanks(v, "do_not_translate")

    @model_validator(mode="after")
    def _supported(self) -> Brand:
        for name, market in self.markets.items():
            lang = language_of(name)
            if lang not in SUPPORTED:
                raise ValueError(
                    f"market {name!r}: target language {lang!r} is not supported "
                    f"(supported: {', '.join(SUPPORTED)})"
                )
            if market.address is not None and lang != "nl":
                raise ValueError(f"market {name!r}: `address` is a Dutch-only rule")
        return self

    def market(self, name: str) -> Market:
        if name not in self.markets:
            known = ", ".join(sorted(self.markets))
            raise BrandError(f"market {name!r} is not in the brand file (markets: {known})")
        return self.markets[name]


def load_brand(path: str | Path) -> Brand:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        raw = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - a SafeLoader subclass
    except OSError as exc:
        raise BrandError(f"cannot read brand file {p}: {exc.strerror}") from None
    except UnicodeDecodeError:
        raise BrandError(f"brand file {p} is not valid UTF-8") from None
    except yaml.YAMLError as exc:
        raise BrandError(f"brand file {p} is not valid YAML: {exc}") from None
    except (TypeError, RecursionError) as exc:  # an unhashable key, or nesting too deep
        raise BrandError(f"brand file {p} is not valid YAML: {type(exc).__name__}") from None
    return parse_brand(raw, str(p))


def parse_brand(raw: object, where: str = "brand") -> Brand:
    if not isinstance(raw, dict):
        raise BrandError(f"{where}: expected a mapping at the top level")
    try:
        return Brand.model_validate(raw)
    except ValueError as exc:
        raise BrandError(f"{where}: {exc}") from None
