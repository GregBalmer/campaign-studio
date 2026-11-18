"""The campaign brief: what the client hands us.

A brief is JSON. JSON was chosen over YAML so the only third-party dependency
stays Pillow. Validation returns plain-language problems a creative team can fix,
not stack traces.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Only languages the bundled fonts can set. Korean and Chinese need their own
# Noto fonts in studio/fonts before they can be added here.
LANGUAGE_NAMES = {
    "en": "English", "ja": "Japanese", "de": "German", "fr": "French",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "sv": "Swedish",
}

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class BriefError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        brief = json.load(fh)
    validate(brief)
    return brief


def validate(brief: dict) -> None:
    problems: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            problems.append(msg)

    need(bool(str(brief.get("campaign", "")).strip()), "Give the campaign a name.")
    need(bool(str(brief.get("message", "")).strip()), "Add the campaign message.")
    need(bool(str(brief.get("audience", "")).strip()), "Describe the target audience.")

    products = brief.get("products") or []
    need(len(products) >= 2, "Add at least two products.")
    ids = set()
    for i, p in enumerate(products, 1):
        need(bool(str(p.get("id", "")).strip()), f"Product {i} needs an id.")
        need(bool(str(p.get("name", "")).strip()), f"Product {i} needs a name.")
        ids.add(p.get("id"))
    need(len(ids) == len(products), "Each product needs its own id.")

    markets = brief.get("markets") or []
    need(len(markets) >= 1, "Add at least one market.")
    for m in markets:
        need(bool(m.get("region")), "Each market needs a region.")
        need(m.get("language") in LANGUAGE_NAMES,
             f"Market {m.get('region', '?')}: '{m.get('language')}' isn't supported yet. "
             f"Supported: {', '.join(LANGUAGE_NAMES.values())}.")

    brand = brief.get("brand") or {}
    need(bool(brand.get("name")), "Add the brand name.")
    colors = brand.get("colors") or {}
    for key in ("primary", "accent"):
        need(bool(HEX.match(str(colors.get(key, "")))), f"Brand colour '{key}' must look like #1A2B3C.")

    if problems:
        raise BriefError(problems)


def source_language(brief: dict) -> str:
    return brief.get("message_language", "en")


def languages(brief: dict) -> list[str]:
    """Every language the campaign ships in, source language first."""
    out = [source_language(brief)]
    for m in brief.get("markets", []):
        if m["language"] not in out:
            out.append(m["language"])
    return out
