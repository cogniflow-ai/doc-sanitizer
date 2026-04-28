"""
Encrypted SQLite secret store.

Schema notes:
 * `original_term` is stored *encrypted* with Fernet (AES-128-CBC + HMAC).
 * `term_lookup_hash` is HMAC-SHA256(master_key, lower(original_term)) — used
   for O(1) duplicate-detection without leaking plaintext.
 * `token` is a deterministic opaque identifier (e.g. `__TERM_42__`); it is NOT
   secret, so we keep it plaintext for fast substitution.
 * Patterns are user-defined regex labels; not encrypted (no PII expected).
 * The DB file itself is created under the user data directory with restrictive
   permissions. SQLite's `secure_delete` PRAGMA is enabled so deleted rows do
   not leave plaintext in the file (we still write encrypted bytes, but this
   is defence-in-depth).

Migration:
 If a legacy plaintext `sanitiser.db` is present alongside the project, it is
 imported once and renamed to `sanitiser.db.legacy.bak`.
"""
from __future__ import annotations

import hmac
import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from doc_sanitizer import crypto, paths


_LOCK = threading.RLock()


def _conn(db_file: Path) -> sqlite3.Connection:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file), isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA secure_delete = ON")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _hash_term(term: str) -> str:
    """HMAC-SHA256 of lower(term) keyed by the master key — for lookup only."""
    key = crypto.get_or_create_master_key()
    return hmac.new(key, term.lower().encode("utf-8"), hashlib.sha256).hexdigest()


class SecretStore:
    """Encrypted persistence layer for the dictionary and user patterns."""

    def __init__(self, db_file: Path | None = None) -> None:
        self.db_file = Path(db_file) if db_file else paths.db_path()
        self._init_schema()
        self._maybe_migrate_legacy()

    # ── connection helper ───────────────────────────────────────────────────
    @contextmanager
    def _open(self) -> Iterator[sqlite3.Connection]:
        with _LOCK:
            conn = _conn(self.db_file)
            try:
                yield conn
            finally:
                conn.close()

    # ── schema ──────────────────────────────────────────────────────────────
    def _init_schema(self) -> None:
        with self._open() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS dictionary (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    term_lookup_hash  TEXT UNIQUE NOT NULL,
                    original_term_enc BLOB NOT NULL,
                    token             TEXT UNIQUE NOT NULL,
                    created_utc       TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_dict_token ON dictionary(token);

                CREATE TABLE IF NOT EXISTS patterns (
                    id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    name  TEXT NOT NULL,
                    regex TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sequence (
                    id       INTEGER PRIMARY KEY CHECK (id = 1),
                    next_val INTEGER NOT NULL DEFAULT 1
                );
                INSERT OR IGNORE INTO sequence (id, next_val) VALUES (1, 1);

                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
            paths.restrict_file(self.db_file)

    def _maybe_migrate_legacy(self) -> None:
        """One-shot import from the old plaintext sanitiser.db (if found)."""
        with self._open() as c:
            done = c.execute(
                "SELECT value FROM meta WHERE key = 'legacy_migrated'"
            ).fetchone()
            if done and done["value"] == "1":
                return
        # Look for sanitiser.db next to the package on disk (project working dir)
        here = Path.cwd()
        candidates = [here / "sanitiser.db", Path(__file__).resolve().parent.parent / "sanitiser.db"]
        legacy = next((p for p in candidates if p.exists()), None)
        if not legacy:
            with self._open() as c:
                c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('legacy_migrated','1')")
            return

        try:
            old = sqlite3.connect(legacy)
            old.row_factory = sqlite3.Row
            try:
                rows = old.execute(
                    "SELECT original_term, token FROM dictionary"
                ).fetchall()
                pats = old.execute("SELECT name, regex FROM patterns").fetchall()
                seq = old.execute("SELECT next_val FROM sequence WHERE id=1").fetchone()
            finally:
                old.close()

            for r in rows:
                self.add_term(r["original_term"], token=r["token"])
            for p in pats:
                self.add_pattern(p["name"], p["regex"])
            if seq:
                with self._open() as c:
                    c.execute("UPDATE sequence SET next_val = ? WHERE id = 1",
                              (max(seq["next_val"], 1),))
            backup = legacy.with_suffix(".db.legacy.bak")
            try:
                legacy.rename(backup)
            except OSError:
                # Best effort — leave original in place
                pass
        finally:
            with self._open() as c:
                c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('legacy_migrated','1')")

    # ── token allocator ─────────────────────────────────────────────────────
    def _next_token(self, c: sqlite3.Connection) -> str:
        row = c.execute("SELECT next_val FROM sequence WHERE id = 1").fetchone()
        val = int(row["next_val"])
        c.execute("UPDATE sequence SET next_val = ? WHERE id = 1", (val + 1,))
        return f"__TERM_{val}__"

    # ── dictionary ─────────────────────────────────────────────────────────
    def add_term(self, term: str, token: str | None = None) -> dict:
        term = term.strip()
        if not term:
            raise ValueError("term must be non-empty")
        h = _hash_term(term)
        enc = crypto.encrypt(term)
        with self._open() as c:
            existing = c.execute(
                "SELECT id, token, original_term_enc FROM dictionary "
                "WHERE term_lookup_hash = ?",
                (h,),
            ).fetchone()
            if existing:
                return {
                    "id": existing["id"],
                    "original_term": crypto.decrypt(existing["original_term_enc"]),
                    "token": existing["token"],
                }
            tok = token or self._next_token(c)
            c.execute(
                "INSERT INTO dictionary (term_lookup_hash, original_term_enc, token) "
                "VALUES (?, ?, ?)",
                (h, enc, tok),
            )
            new_id = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            return {"id": new_id, "original_term": term, "token": tok}

    def get_dictionary(self) -> list[dict]:
        with self._open() as c:
            rows = c.execute(
                "SELECT id, original_term_enc, token FROM dictionary ORDER BY id"
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            try:
                term = crypto.decrypt(r["original_term_enc"])
            except RuntimeError:
                # Skip corrupted/legacy entries rather than crash the whole call
                continue
            out.append({"id": r["id"], "original_term": term, "token": r["token"]})
        return out

    def delete_term(self, entry_id: int) -> None:
        with self._open() as c:
            c.execute("DELETE FROM dictionary WHERE id = ?", (entry_id,))

    def export_dictionary(self) -> dict:
        return {"dictionary": self.get_dictionary()}

    def import_dictionary(self, data: dict) -> int:
        entries = data.get("dictionary", []) or []
        n = 0
        for e in entries:
            try:
                self.add_term(e["original_term"], token=e.get("token"))
                n += 1
            except Exception:
                continue
        return n

    # ── patterns ────────────────────────────────────────────────────────────
    def get_patterns(self) -> list[dict]:
        with self._open() as c:
            rows = c.execute(
                "SELECT id, name, regex FROM patterns ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    def add_pattern(self, name: str, regex: str) -> None:
        import re
        re.compile(regex)  # validate, raises re.error on bad input
        with self._open() as c:
            c.execute("INSERT INTO patterns (name, regex) VALUES (?, ?)", (name, regex))

    def delete_pattern(self, pat_id: int) -> None:
        with self._open() as c:
            c.execute("DELETE FROM patterns WHERE id = ?", (pat_id,))


# ── module-level singleton (for compatibility with the old db module API) ───
_default: SecretStore | None = None


def default_store() -> SecretStore:
    global _default
    if _default is None:
        _default = SecretStore()
    return _default


def reset_default_store() -> None:
    """For tests — reload the singleton from disk."""
    global _default
    _default = None
