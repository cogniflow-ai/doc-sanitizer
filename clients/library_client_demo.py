"""
Library demo — calls the doc_sanitizer Python library directly (in-process).

No HTTPS, no subprocess, no token. This is the fastest mode and the right
one when the calling code already runs as the data owner. Demonstrates:

  1. Building / querying the dictionary
  2. Masking and unmasking plain text (a Markdown file)
  3. Masking and unmasking an Office file (.docx) as bytes-in / bytes-out
  4. Detecting candidate sensitive terms WITHOUT modifying state
  5. Exporting / re-importing the dictionary as JSON

Run:
    pip install -e .       # one-time, in the repo root
    python clients/library_client_demo.py

The demo isolates its state under a throw-away temp directory so it never
touches the user's real encrypted store.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ── isolate state into a temp dir BEFORE importing doc_sanitizer ──────────
_TMP = Path(tempfile.mkdtemp(prefix="docsan-lib-demo-"))
os.environ["DOC_SANITIZER_HOME"] = str(_TMP)

# Make sibling fixture importable without the package install, and let
# `from doc_sanitizer import …` work even if you haven't run `pip install -e .`
# (resolve to the source tree one level up).
_PROJECT_ROOT = HERE.parent
for p in (str(HERE), str(_PROJECT_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
from _sample_docx import make_sample_docx  # type: ignore

from doc_sanitizer import Sanitizer


def main() -> int:
    print(f"[home]   DOC_SANITIZER_HOME = {_TMP}")

    sample_docx = make_sample_docx()
    sample_md   = HERE / "sample.md"
    print(f"[sample] {sample_docx.name}  ({sample_docx.stat().st_size} bytes)")
    print(f"[sample] {sample_md.name}    ({sample_md.stat().st_size} bytes)\n")

    s = Sanitizer()

    # ── 1. seed dictionary ─────────────────────────────────────────────────
    seed = ["Acme Corporation", "Mario Rossi",
            "mario.rossi@acme.example", "+39 02 1234 5678", "ORD-90215"]
    for term in seed:
        s.add_term(term)
    print(f"[1]  dictionary now has {len(s.dictionary())} entries:")
    for e in s.dictionary():
        print(f"        {e['token']:>12}  ->  {e['original_term']}")
    print()

    # ── 2. .md round-trip ──────────────────────────────────────────────────
    md_text = sample_md.read_text(encoding="utf-8")
    masked  = s.mask_text(md_text)
    restored = s.unmask_text(masked)
    for term in seed:
        assert term not in masked, f"plaintext leaked for {term!r}"
    assert restored == md_text, ".md byte-exact round-trip failed"
    print("[2]  .md mask+unmask is byte-exact, no plaintext leaks\n")

    # ── 3. .docx round-trip (bytes-in, bytes-out) ─────────────────────────
    masked_docx_bytes   = s.mask_file(sample_docx.read_bytes(), ext=".docx")
    rehydrated_docx_bytes = s.unmask_file(masked_docx_bytes, ext=".docx")

    out_masked = HERE / "lib_sample.masked.docx"
    out_rehyd  = HERE / "lib_sample.rehydrated.docx"
    out_masked.write_bytes(masked_docx_bytes)
    out_rehyd.write_bytes(rehydrated_docx_bytes)

    from docx import Document
    def _text(b: bytes) -> str:
        d = Document(io.BytesIO(b))
        return "\n".join(p.text for p in d.paragraphs)

    masked_text = _text(masked_docx_bytes)
    rehyd_text  = _text(rehydrated_docx_bytes)
    for term in seed:
        assert term not in masked_text, f"masked .docx still contains {term!r}"
        assert term in rehyd_text,      f"rehydrated .docx missing {term!r}"
    print(f"[3]  .docx round-trip OK")
    print(f"        masked     -> {out_masked.name}")
    print(f"        rehydrated -> {out_rehyd.name}\n")

    # ── 4. detection without persisting anything ──────────────────────────
    candidates = s.detect("Hello Jane Doe, your invoice is at INV-9876")
    print(f"[4]  detect() candidates: {candidates}\n")

    # ── 5. dictionary export / import (JSON portability) ──────────────────
    snapshot = s.export_dictionary()
    out_json = HERE / "lib_dictionary.json"
    out_json.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"[5]  exported dictionary -> {out_json.name}")

    # Round-trip into a fresh Sanitizer with a different db path
    fresh_db = _TMP / "fresh.db"
    s2 = Sanitizer(db_path=fresh_db)
    n = s2.import_dictionary(snapshot)
    assert n == len(seed), f"expected {len(seed)} imported, got {n}"
    assert s2.unmask_text(masked) == md_text, \
        "imported dictionary failed to rehydrate previously-masked text"
    print(f"        re-imported into fresh DB and rehydrated the masked .md exactly\n")

    print("All library demo steps passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
