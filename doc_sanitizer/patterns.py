"""
Fixed regex patterns applied during sensitive-term detection.
Each entry: (label, pattern). Run alongside any user-defined patterns from the DB.
"""
from __future__ import annotations

FIXED_PATTERNS: list[tuple[str, str]] = [
    ("Email",
     r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    ("UUID",
     r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    ("Capitalised Sequence",
     r"\b[A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20})+\b"),
    ("All-Caps Acronym",
     r"\b[A-Z]{2,6}\b"),
    ("Alphanumeric ID",
     r"\b[A-Z]{1,6}[-_][0-9]{2,10}\b"),
    ("IT Fiscal Code",
     r"\b[A-Z]{6}[0-9]{2}[A-EHLMPRST][0-9]{2}[A-Z][0-9]{3}[A-Z]\b"),
    ("VAT Number",
     r"\b[A-Z]{2}[0-9A-Z]{8,12}\b"),
    ("Long Number",
     r"\b\d{5,}\b"),
    ("Phone",
     r"(?:\+\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}"),
    ("IBAN",
     r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}[A-Z0-9]{0,16}\b"),
]
