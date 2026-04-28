"""
OpenAI Privacy Filter — three illustrative use cases.

The OpenAI Privacy Filter (OPF) is a small ML-based PII tagger published at
https://github.com/openai/privacy-filter. It loads a model from HuggingFace
(~50 MB on first run, then cached) and returns labelled entity spans with
confidence scores. The library exposes high-level redact_text / unredact_text
helpers that swap entities for placeholders such as [PERSON_1] / [EMAIL_1].

This script demonstrates:

  USE CASE 1 — Basic PII detection on an email.
                (What does OPF flag, and at what confidence?)

  USE CASE 2 — Operating-point tuning on a call-centre transcript.
                Same input, three thresholds (loose / default / strict).
                Shows the precision/recall trade-off you control with min_score.

  USE CASE 3 — OPF + doc-sanitizer integration.
                Use OPF to *find* PII; use doc-sanitizer to *substitute* it
                with deterministic tokens that survive across multiple
                independent texts and persist in an encrypted store.
                This is the pattern you want when you need stable tokens
                across an entire document corpus or session, not the
                per-text [EMAIL_1] OPF gives you out of the box.

Run (from this directory):
    pip install privacy-filter
    pip install -e ../..        # install doc_sanitizer from the repo root
    python opf_demo.py

If `privacy-filter` is not installed the script prints install instructions
and exits cleanly — it does not pretend to do detection without the model.

The first call to `get_classifier()` downloads ~50 MB and may take 30–60s
on a cold start; subsequent runs reuse the HF cache under
~/.cache/huggingface/.
"""
from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ── 0. preflight: OPF available? ────────────────────────────────────────────
try:
    from privacy_filter import (
        ENTITY_SHORT_NAMES,
        PiiStore,
        get_classifier,
        redact_text,
        unredact_text,
    )
except ModuleNotFoundError:
    print(textwrap.dedent("""\
        privacy-filter is not installed in this Python environment.

        Install it with:
            pip install privacy-filter

        Then re-run this script.
        """))
    sys.exit(1)


def _hr(label: str = "") -> None:
    bar = "─" * 78
    if label:
        print(f"\n{bar}\n  {label}\n{bar}")
    else:
        print(bar)


def _summarize(masked: str, store: PiiStore) -> None:
    """Print the masked text + the placeholder->original mapping."""
    print(masked.rstrip())
    print()
    print("placeholder mapping:")
    for placeholder, original in sorted(store.forward.items()):
        print(f"    {placeholder:<14}  ->  {original}")


# ─────────────────────────────────────────────────────────────────────────────
# USE CASE 1 — basic detection
# ─────────────────────────────────────────────────────────────────────────────
def use_case_1_basic_detection(clf) -> None:
    _hr("USE CASE 1 — basic PII detection on a short email")

    text = (HERE / "sample_email.txt").read_text(encoding="utf-8")
    entities = clf(text)

    print(f"input: sample_email.txt  ({len(text)} chars)")
    print(f"OPF returned {len(entities)} raw entity spans:\n")

    # Print raw entity spans grouped by type, sorted by score descending.
    by_type: dict[str, list[dict]] = {}
    for e in entities:
        by_type.setdefault(e["entity_group"], []).append(e)
    for typ, ents in by_type.items():
        short = ENTITY_SHORT_NAMES.get(typ, typ)
        print(f"  [{short}]  ({len(ents)} spans)")
        for e in sorted(ents, key=lambda x: -float(x["score"]))[:5]:
            score = float(e["score"])
            print(f"      score={score:.4f}   pos={e['start']:>3}-{e['end']:<3}   {e['word']!r}")
    print()

    # Now show what redact_text produces with the default min_score=0.8
    store = PiiStore()
    masked = redact_text(text, entities, store)
    _hr("USE CASE 1 — masked output")
    _summarize(masked, store)

    # Round-trip back
    restored = unredact_text(masked, store)
    assert restored == text, "OPF round-trip failed (default threshold)"
    print("\n[ok] unredact_text() restored the original text byte-for-byte")


# ─────────────────────────────────────────────────────────────────────────────
# USE CASE 2 — operating-point tuning
# ─────────────────────────────────────────────────────────────────────────────
def use_case_2_thresholds(clf) -> None:
    _hr("USE CASE 2 — operating-point tuning on a transcript")
    text = (HERE / "sample_transcript.txt").read_text(encoding="utf-8")
    entities = clf(text)
    print(f"input: sample_transcript.txt ({len(text)} chars, "
          f"{len(entities)} raw entities detected)\n")

    # Three thresholds illustrate the trade-off:
    #   loose:   catch more (higher recall, more false positives)
    #   default: OPF's recommended setting
    #   strict:  catch only very confident hits (higher precision, may miss some)
    for label, threshold in [("loose (0.50)", 0.50),
                             ("default (0.80)", 0.80),
                             ("strict (0.95)", 0.95)]:
        store = PiiStore()
        masked = redact_text(text, entities, store, min_score=threshold)
        n = len(store.forward)
        print(f"--- threshold = {label}  →  {n} placeholders inserted")
        # Show only the first ~6 lines so the output stays readable
        for line in masked.splitlines()[:6]:
            print(f"    {line}")
        if len(masked.splitlines()) > 6:
            print(f"    ... ({len(masked.splitlines()) - 6} more lines)")
        print()


# ─────────────────────────────────────────────────────────────────────────────
# USE CASE 3 — OPF + doc-sanitizer integration
# ─────────────────────────────────────────────────────────────────────────────
def use_case_3_doc_sanitizer_integration(clf) -> None:
    _hr("USE CASE 3 — OPF detects, doc-sanitizer substitutes")

    # Allow running directly from the repo without `pip install -e .`
    repo_root = HERE.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from doc_sanitizer import Sanitizer
    except ModuleNotFoundError:
        print("doc_sanitizer is not importable — skipping use case 3.")
        print("Run from this directory: pip install -e ../..")
        return

    # Use a throw-away DOC_SANITIZER_HOME so we don't touch the real DB.
    import shutil
    import tempfile
    tmp_home = Path(tempfile.mkdtemp(prefix="opf-docsan-"))
    os.environ["DOC_SANITIZER_HOME"] = str(tmp_home)
    print(f"isolated doc-sanitizer state: {tmp_home}\n")

    try:
        # Reset the doc_sanitizer singleton so it picks up the new home
        from doc_sanitizer import secrets_store
        secrets_store.reset_default_store()
        s = Sanitizer()

        # Two independent texts that contain overlapping PII (Mario Rossi, etc.)
        text_a = (HERE / "sample_email.txt").read_text(encoding="utf-8")
        text_b = (HERE / "sample_transcript.txt").read_text(encoding="utf-8")

        # IMPORTANT: OPF's classifier returns sub-token spans (e.g. an email may
        # come back as two pieces: "mario.rossi@acme" + ".example"; a 10-digit
        # number may come back as "9928374" + "65" + "1"). Feeding those raw
        # fragments to doc-sanitizer would create dictionary entries like "1"
        # or "8" that match characters inside OTHER tokens — a corruption loop.
        #
        # Fix: let OPF's `redact_text` merge contiguous spans first, then read
        # the merged originals out of `PiiStore.forward`. We additionally
        # restrict to types we want to substitute and skip very short terms.
        substitutable = {"private_person", "private_email", "private_phone",
                         "private_address", "private_url", "account_number"}

        def opf_merged_terms(t: str, threshold: float = 0.85,
                             min_len: int = 3) -> list[str]:
            ents = clf(t)
            store = PiiStore()
            redact_text(t, ents, store, min_score=threshold,
                        entity_types=list(substitutable))
            terms: list[str] = []
            seen: set[str] = set()
            for original in store.forward.values():
                term = original.strip(" \t\n\r.,;:")
                if len(term) < min_len:
                    continue
                if term.lower() in seen:
                    continue
                seen.add(term.lower())
                terms.append(term)
            return terms

        terms_a = opf_merged_terms(text_a)
        terms_b = opf_merged_terms(text_b)
        print(f"OPF found {len(terms_a)} substitutable terms in email")
        print(f"OPF found {len(terms_b)} substitutable terms in transcript\n")

        # Feed all terms into the doc-sanitizer dictionary. Stable tokens are
        # assigned ONCE per unique term, regardless of how many texts mention it.
        for t in terms_a + terms_b:
            s.add_term(t)

        masked_a = s.mask_text(text_a)
        masked_b = s.mask_text(text_b)

        # Show the dictionary — note the same token reused across both texts
        print("doc-sanitizer dictionary (deterministic tokens):")
        for e in s.dictionary():
            print(f"    {e['token']:>14}  ->  {e['original_term']}")
        print()

        print("--- masked email (first 6 lines) ---")
        for line in masked_a.splitlines()[:6]:
            print(f"  {line}")
        print()
        print("--- masked transcript (first 6 lines) ---")
        for line in masked_b.splitlines()[:6]:
            print(f"  {line}")
        print()

        # Round-trip both
        assert s.unmask_text(masked_a) == text_a, "email round-trip failed"
        assert s.unmask_text(masked_b) == text_b, "transcript round-trip failed"
        print("[ok] both texts round-trip exactly via doc-sanitizer")
        print("[ok] tokens are STABLE across documents — '__TERM_N__' for the")
        print("     same person/email/phone in any text, persisted in the")
        print("     encrypted SQLite store under DOC_SANITIZER_HOME.")
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    print("Loading the OPF classifier (downloads ~50MB on first run) ...")
    clf = get_classifier()
    print("Classifier ready.\n")

    use_case_1_basic_detection(clf)
    use_case_2_thresholds(clf)
    use_case_3_doc_sanitizer_integration(clf)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
