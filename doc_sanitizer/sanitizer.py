"""
High-level facade.

Typical usage:

    from doc_sanitizer import Sanitizer

    s = Sanitizer()
    masked = s.mask_text("Acme Corp ships widgets")     # str
    restored = s.unmask_text(masked)                    # str

    masked_bytes = s.mask_file(open("doc.docx", "rb").read(), ext=".docx")
    restored_bytes = s.unmask_file(masked_bytes, ext=".docx")

The Sanitizer holds a reference to a SecretStore (encrypted SQLite).
By default it uses the user-scoped store under the OS data dir; pass
`db_path` to point at a project-local store.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO, Iterable

from doc_sanitizer import extractor, obfuscator
from doc_sanitizer.secrets_store import SecretStore, default_store


class Sanitizer:
    def __init__(self, db_path: str | Path | None = None,
                 store: SecretStore | None = None) -> None:
        if store is not None:
            self.store = store
        elif db_path is not None:
            self.store = SecretStore(Path(db_path))
        else:
            self.store = default_store()

    # ── dictionary management ───────────────────────────────────────────────
    def add_term(self, term: str, token: str | None = None) -> dict:
        return self.store.add_term(term, token=token)

    def remove_term(self, entry_id: int) -> None:
        self.store.delete_term(entry_id)

    def dictionary(self) -> list[dict]:
        return self.store.get_dictionary()

    def patterns(self) -> list[dict]:
        return self.store.get_patterns()

    def add_pattern(self, name: str, regex: str) -> None:
        self.store.add_pattern(name, regex)

    def remove_pattern(self, pat_id: int) -> None:
        self.store.delete_pattern(pat_id)

    def export_dictionary(self) -> dict:
        return self.store.export_dictionary()

    def import_dictionary(self, data: dict) -> int:
        return self.store.import_dictionary(data)

    # ── detection ───────────────────────────────────────────────────────────
    def detect(self, text: str) -> list[str]:
        return obfuscator.detect_terms(text, self.store.get_patterns())

    def detect_in_file(self, data: bytes | BinaryIO, ext: str) -> list[str]:
        buf = data if hasattr(data, "read") else io.BytesIO(data)
        text = extractor.extract_text(buf, ext.lower())
        return self.detect(text)

    # ── mask / unmask (text) ────────────────────────────────────────────────
    def mask_text(self, text: str, *, auto_add: bool = False) -> str:
        """
        Mask `text` using the current dictionary. If `auto_add=True`, every
        candidate detected in the text is added to the dictionary first — useful
        for one-shot programmatic masking without an interactive review step.
        """
        if auto_add:
            for term in self.detect(text):
                self.store.add_term(term)
        return obfuscator.obfuscate_text(text, self.store.get_dictionary())

    def unmask_text(self, text: str) -> str:
        return obfuscator.rehydrate_text(text, self.store.get_dictionary())

    # ── mask / unmask (file bytes) ──────────────────────────────────────────
    def mask_file(self, data: bytes | BinaryIO, ext: str,
                  *, auto_add: bool = False) -> bytes:
        """
        Mask an office file (.docx/.pptx/.xlsx) or any other text file in-place.
        Returns the masked file as bytes.
        """
        ext = ext.lower()
        raw = data.read() if hasattr(data, "read") else data
        if auto_add:
            for term in self.detect_in_file(raw, ext):
                self.store.add_term(term)
        if ext in extractor.OFFICE_EXTS:
            return extractor.obfuscate_file(io.BytesIO(raw), ext, self.store.get_dictionary())
        # Plain text path
        text = raw.decode("utf-8", errors="replace")
        return obfuscator.obfuscate_text(text, self.store.get_dictionary()).encode("utf-8")

    def unmask_file(self, data: bytes | BinaryIO, ext: str) -> bytes:
        ext = ext.lower()
        raw = data.read() if hasattr(data, "read") else data
        if ext in extractor.OFFICE_EXTS:
            return extractor.rehydrate_file(io.BytesIO(raw), ext, self.store.get_dictionary())
        text = raw.decode("utf-8", errors="replace")
        return obfuscator.rehydrate_text(text, self.store.get_dictionary()).encode("utf-8")


# ── module-level convenience helpers ────────────────────────────────────────

def mask_text(text: str, *, auto_add: bool = False) -> str:
    return Sanitizer().mask_text(text, auto_add=auto_add)


def unmask_text(text: str) -> str:
    return Sanitizer().unmask_text(text)


def mask_file(data: bytes | BinaryIO, ext: str, *, auto_add: bool = False) -> bytes:
    return Sanitizer().mask_file(data, ext, auto_add=auto_add)


def unmask_file(data: bytes | BinaryIO, ext: str) -> bytes:
    return Sanitizer().unmask_file(data, ext)
