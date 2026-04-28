"""
Core obfuscation and rehydration logic. Pure-functional — no I/O.
"""
from __future__ import annotations

import re
from typing import Iterable

from doc_sanitizer.patterns import FIXED_PATTERNS


def detect_terms(text: str, user_patterns: Iterable[dict] | None = None) -> list[str]:
    """Scan text and return deduplicated candidate sensitive terms."""
    all_patterns: list[tuple[str, str]] = list(FIXED_PATTERNS)
    if user_patterns:
        for p in user_patterns:
            all_patterns.append((p["name"], p["regex"]))

    seen: set[str] = set()
    candidates: list[str] = []
    for _name, pattern in all_patterns:
        try:
            for match in re.finditer(pattern, text):
                term = match.group(0).strip()
                if term and term.lower() not in seen:
                    seen.add(term.lower())
                    candidates.append(term)
        except re.error:
            continue
    return candidates


def obfuscate_text(text: str, dictionary: list[dict]) -> str:
    """Replace each dictionary term with its token (case-insensitive, longest-first)."""
    sorted_entries = sorted(dictionary, key=lambda e: len(e["original_term"]), reverse=True)
    for entry in sorted_entries:
        pattern = re.compile(re.escape(entry["original_term"]), re.IGNORECASE)
        text = pattern.sub(entry["token"], text)
    return text


def rehydrate_text(text: str, dictionary: list[dict]) -> str:
    """Replace tokens with the canonical original term."""
    for entry in dictionary:
        text = text.replace(entry["token"], entry["original_term"])
    return text
