# Example — OpenAI Privacy Filter integration

A single self-contained script (`opf_demo.py`) that demonstrates three
distinct patterns for using the [OpenAI Privacy Filter](https://github.com/openai/privacy-filter)
("OPF") library — including how to combine OPF with this repo's
`doc_sanitizer` for stable cross-document tokens.

## Use cases

1. **Basic detection** — feed `sample_email.txt` to OPF, dump the entity spans
   it found grouped by type with confidence scores, then redact and round-trip.

2. **Operating-point tuning** — feed `sample_transcript.txt` to OPF and call
   `redact_text` at three thresholds (0.50 / 0.80 / 0.95). Shows the
   precision/recall trade-off you control with `min_score`.

3. **OPF + doc-sanitizer integration** — OPF *finds* PII; doc-sanitizer
   *substitutes* it with deterministic tokens. The same person/email gets the
   same `__TERM_N__` across multiple texts, persisted in the encrypted store.
   The merged-spans gotcha (OPF returns sub-token fragments like `9928374` +
   `65` + `1`) is documented inline in the script.

## Run

```bash
pip install privacy-filter
pip install -e ../..        # install doc_sanitizer from the repo root
python opf_demo.py
```

The first OPF call downloads ~50 MB from HuggingFace and caches it under
`~/.cache/huggingface/`; subsequent runs are instant.

## What this script does NOT do

- It does not call the OpenAI API — OPF is a local tagger, not an LLM.
  Use case 3 stops at "produce a masked string ready to send to a model".
- It does not pretend to detect PII without OPF installed; if the import
  fails, the script prints install instructions and exits cleanly.

## Why this lives in the doc-sanitizer repo

This example is course material for the *Information Masking* Udemy course
and ships alongside the doc-sanitizer library it integrates with.
