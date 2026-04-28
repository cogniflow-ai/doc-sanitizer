"""Compatibility shim — re-exports from doc_sanitizer.obfuscator."""
from doc_sanitizer.obfuscator import detect_terms, obfuscate_text, rehydrate_text

__all__ = ["detect_terms", "obfuscate_text", "rehydrate_text"]
