"""Compatibility shim — re-exports from doc_sanitizer.extractor."""
from doc_sanitizer.extractor import (
    OFFICE_EXTS,
    extract_text,
    obfuscate_file,
    rehydrate_file,
)

__all__ = ["OFFICE_EXTS", "extract_text", "obfuscate_file", "rehydrate_file"]
