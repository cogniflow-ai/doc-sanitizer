# clients/ — example integrations

Two minimal, runnable scripts that show how to call doc-sanitizer from
external code:

| Script                     | Mode                              | When to use it                                        |
|----------------------------|-----------------------------------|-------------------------------------------------------|
| `library_client_demo.py`   | In-process Python library         | Same machine, same Python, you own the data.          |
| `https_client_demo.py`     | Local HTTPS API (`stdlib only`)   | Cross-process / different language / sandboxed caller. |

Both demos round-trip:

* `sample.md`  — checked-in plain Markdown
* `sample.docx` — generated programmatically by `_sample_docx.py` on first run

…and assert that the masked file contains *no* plaintext of the seed terms,
and the unmasked file restores them all.

## Run

From the repository root, with the dependencies installed:

```bash
python clients/library_client_demo.py
python clients/https_client_demo.py
```

The HTTPS demo auto-spawns the API server in a subprocess against a
**throw-away** `DOC_SANITIZER_HOME`, so it never touches your real encrypted
store. Pass `--no-spawn --port <P> --data-dir <D>` to point at a server you
already have running.

## Pattern: deterministic seeding vs auto-detection

The demos *seed the dictionary explicitly* with the terms they want masked,
rather than calling the endpoints with `auto_add=true`. This is intentional:

`auto_add=true` runs the regex detector and adds every candidate (including
edge cases like `ORD` matching inside `order`). That is fine for a quick
"mask anything that looks remotely sensitive" pass, but it is **not** what
you want when you need a byte-exact round-trip — case-insensitive
substitution can rewrite the casing of bystander text.

For deterministic substitution: review candidates, then add canonical terms
explicitly via `Sanitizer.add_term(...)` or `POST /v1/dictionary`.
