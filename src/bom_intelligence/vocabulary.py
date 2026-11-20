"""Configurable BOM field vocabulary (header aliases and keywords).

Aliases are data (``data/aliases.json`` by default, or any JSON file with the same
shape) so parsers never hard-code header text.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import resources
from pathlib import Path


class FieldCategory(StrEnum):
    PART_NUMBER = "part_number"
    PART_NAME = "part_name"
    SUPPLIER = "supplier"
    COST = "cost"
    SCHEDULE = "schedule"


_PARENS = re.compile(r"[\(（\[［【].*?[\)）\]］】]")
_STRIP = re.compile(r"[\s\.\,\-_:：・/#＃\*　]+")
_ASCII_ONLY = re.compile(r"^[a-z0-9]+$")


def normalize_label(text: str, *, keep_parenthesized: bool = False) -> str:
    """Normalize a label for alias matching (NFKC, case, punctuation, brackets)."""
    value = unicodedata.normalize("NFKC", text).lower()
    if not keep_parenthesized:
        value = _PARENS.sub("", value)
    return _STRIP.sub("", value)


@dataclass(frozen=True)
class AliasMatch:
    category: FieldCategory
    alias: str
    subtype: str | None
    exact: bool


@dataclass(frozen=True)
class Vocabulary:
    """Lookup table from normalized alias to field category (+ optional subtype)."""

    entries: dict[str, tuple[FieldCategory, str, str | None]] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, object]) -> Vocabulary:
        entries: dict[str, tuple[FieldCategory, str, str | None]] = {}
        for key, items in data.items():
            if key.startswith("_"):
                continue
            category = FieldCategory(key)
            if not isinstance(items, list):
                raise ValueError(f"aliases for {key!r} must be a list")
            for item in items:
                if isinstance(item, str):
                    alias, subtype = item, None
                elif isinstance(item, list) and len(item) == 2:
                    alias, subtype = str(item[0]), (None if item[1] is None else str(item[1]))
                else:
                    raise ValueError(f"invalid alias entry for {key!r}: {item!r}")
                normalized = normalize_label(alias)
                if not normalized:
                    raise ValueError(f"alias normalizes to empty string: {alias!r}")
                existing = entries.get(normalized)
                if existing is not None and existing[0] is not category:
                    raise ValueError(f"alias {alias!r} maps to both {existing[0]} and {category}")
                entries[normalized] = (category, alias, subtype)
        return cls(entries=entries)

    @classmethod
    def load(cls, path: Path | None = None) -> Vocabulary:
        if path is None:
            text = (
                resources.files("bom_intelligence")
                .joinpath("data/aliases.json")
                .read_text(encoding="utf-8")
            )
        else:
            text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("alias file must contain a JSON object")
        return cls.from_mapping(data)

    def match_header(self, text: str) -> AliasMatch | None:
        """Exact (normalized) header match, or ``None``."""
        normalized = normalize_label(text)
        hit = self.entries.get(normalized)
        if hit is None:
            return None
        return AliasMatch(category=hit[0], alias=hit[1], subtype=hit[2], exact=True)

    def find_keywords(self, text: str) -> list[AliasMatch]:
        """Aliases contained in ``text`` (one per category, longest alias wins).

        Very short ASCII aliases (e.g. ``pn``) are only matched exactly to avoid
        false hits inside ordinary words.
        """
        exact = self.match_header(text)
        if exact is not None:
            return [exact]
        normalized = normalize_label(text, keep_parenthesized=True)
        best: dict[FieldCategory, tuple[str, str, str | None]] = {}
        for alias_norm, (category, alias, subtype) in self.entries.items():
            if _ASCII_ONLY.match(alias_norm) and len(alias_norm) < 4:
                continue
            if alias_norm in normalized:
                current = best.get(category)
                if current is None or len(alias_norm) > len(current[0]):
                    best[category] = (alias_norm, alias, subtype)
        return [
            AliasMatch(category=cat, alias=alias, subtype=subtype, exact=False)
            for cat, (_, alias, subtype) in sorted(best.items(), key=lambda kv: kv[0].value)
        ]


_DEFAULT: Vocabulary | None = None


def default_vocabulary() -> Vocabulary:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Vocabulary.load()
    return _DEFAULT
