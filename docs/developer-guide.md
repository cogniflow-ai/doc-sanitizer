# Cogniflow Privacy Filter — Developer Guide

This document is for engineers who want to:

- Embed Cogniflow Privacy Filter (CPF) as a Python library in another app
- Call the local HTTPS API from a non-Python client
- Extend the detection regexes, encryption scheme, or transport
- Build / sign / release the `.exe` and `.app` artifacts
- Contribute changes back to `cogniflow-ai/doc-sanitizer`

If you just want to *use* CPF as an end user, read
[`user-guide.md`](./user-guide.md) instead.

---

## 1. Architecture at a glance

```
                  ┌──────────────────────────────────────────────────────┐
                  │                Cogniflow Privacy Filter              │
                  │                                                      │
   Web UI ─────►  │  Flask app  ──┐                                      │
                  │               │                                      │
   HTTPS API ──►  │  Flask app  ──┼─►  Sanitizer ◄── public library API  │
                  │               │       │                              │
   CLI ────────►  │  argparse   ──┘       │                              │
                  │                       ▼                              │
                  │                  SecretStore  (encrypted SQLite)     │
                  │                       │                              │
                  │                       ▼                              │
                  │                  crypto.py ── master key              │
                  │                       │     (OS keyring or file)     │
                  └───────────────────────┼──────────────────────────────┘
                                          │
                                  per-user data dir
                                  (sanitizer.db, tls/, api_token, …)
```

Everything funnels through a single `Sanitizer` facade. The Flask UI, the
HTTPS API, and the CLI are all *thin* — none of them contain business
logic. That's deliberate: it makes the library independently usable and
keeps the surface small.

### Key design decisions

| Decision                                          | Rationale                                                      |
|---------------------------------------------------|----------------------------------------------------------------|
| Column-level Fernet, not SQLCipher                | No native deps; survives PyInstaller bundling                  |
| HMAC-SHA256 for term lookup                       | O(1) duplicate detection without decrypting every row          |
| Tokens (e.g. `__TERM_42__`) stored *plaintext*    | They're not secret — they're substitution targets              |
| Refuse non-loopback bind                          | One less footgun. Local-only is a feature, not a default.      |
| Bearer-token, not mTLS                            | Simplest local-app integration. mTLS is a follow-up.           |
| Self-signed cert, valid 5 years                   | No CA needed; rotates rarely on a dev machine                  |
| 25 MiB body cap, 60 rpm per token                 | Cheap DoS protection in the loopback case                      |

For the full rationale see [`../DECISIONS.md`](../DECISIONS.md).

---

## 2. Repository layout

```
doc-sanitizer/
├── doc_sanitizer/              ← the library + Flask UI + API + CLI
│   ├── __init__.py             ← public re-exports
│   ├── sanitizer.py            ← Sanitizer facade + module-level helpers
│   ├── secrets_store.py        ← encrypted SQLite store
│   ├── crypto.py               ← master key + TLS cert generation
│   ├── obfuscator.py           ← pure-functional mask/unmask helpers
│   ├── extractor.py            ← .docx / .pptx / .xlsx text I/O
│   ├── patterns.py             ← built-in regex patterns
│   ├── paths.py                ← per-OS data dir resolution
│   ├── api.py                  ← Flask app for the HTTPS API
│   ├── web.py                  ← Flask app for the Web UI
│   ├── cli.py                  ← argparse entry point
│   ├── templates/              ← Jinja2 templates for the UI
│   └── static/                 ← UI CSS
├── clients/                    ← integration examples
│   ├── library_client_demo.py
│   ├── https_client_demo.py
│   ├── _sample_docx.py
│   ├── sample.md
│   └── README.md
├── examples/openai-privacy-filter/
│   ├── opf_demo.py             ← three OPF use cases
│   ├── sample_email.txt
│   ├── sample_transcript.txt
│   └── README.md
├── tests/test_sanitizer.py     ← pytest suite
├── docs/                       ← user-guide.md, developer-guide.md
├── .github/workflows/build.yml ← CI matrix + binary build
├── pyproject.toml              ← package metadata + entry points
├── doc_sanitizer.spec          ← PyInstaller spec
├── requirements.txt
├── README.md
├── DECISIONS.md
├── LICENSE                     ← MIT
└── app.py / db.py / …          ← thin shims that re-export the package
```

Top-level `app.py`, `db.py`, `obfuscator.py`, `patterns.py`, `extractor.py`
exist so old code doing `import db` or `import obfuscator` keeps working.
**Do not add new code there.** All new code goes inside `doc_sanitizer/`.

---

## 3. Dev environment

```bash
git clone https://github.com/cogniflow-ai/doc-sanitizer.git
cd doc-sanitizer

python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate

pip install -e ".[test,build]"
```

`[test]` adds pytest. `[build]` adds PyInstaller. Both are declared in
`pyproject.toml` under `[project.optional-dependencies]`.

### Run the test suite

```bash
pytest -q
```

Tests use `monkeypatch.setenv("DOC_SANITIZER_HOME", tmpdir)` to isolate
state. There's also a fixture that resets `secrets_store._default` so the
singleton picks up the new home. Don't reach for global state from a test
without resetting it.

### Run from source

```bash
# Web UI
python -m doc_sanitizer.cli ui --port 5001

# HTTPS API
python -m doc_sanitizer.cli api --port 8443

# One-shot
python -m doc_sanitizer.cli mask /path/to/file.docx
```

The packaged binary just wraps `python -m doc_sanitizer.cli`.

---

## 4. The library API

Public surface, exported from `doc_sanitizer/__init__.py`:

```python
from doc_sanitizer import (
    Sanitizer,
    mask_text,
    unmask_text,
    mask_file,
    unmask_file,
    __version__,
)
```

### `Sanitizer`

```python
class Sanitizer:
    def __init__(
        self,
        db_path: str | Path | None = None,
        store: SecretStore | None = None,
    ): ...
```

| Method                                          | Purpose                              |
|-------------------------------------------------|--------------------------------------|
| `add_term(term, token=None) -> dict`            | Add or fetch existing term           |
| `remove_term(entry_id: int)`                    | Delete by ID                         |
| `dictionary() -> list[dict]`                    | All entries, oldest first            |
| `export_dictionary() -> dict`                   | JSON-serializable snapshot           |
| `import_dictionary(snapshot: dict) -> int`      | Returns count imported               |
| `add_pattern(name, regex)`                      | Validate + persist a regex           |
| `remove_pattern(pid: int)`                      | Delete a pattern                     |
| `patterns() -> list[dict]`                      | List user patterns                   |
| `detect(text) -> list[str]`                     | Run patterns, no state change        |
| `detect_in_file(bytes_or_io, ext) -> list[str]` | Same but extracts text first         |
| `mask_text(text, *, auto_add=False) -> str`     | Substitute terms with tokens         |
| `unmask_text(text) -> str`                      | Reverse substitution                 |
| `mask_file(bytes_or_io, ext, *, auto_add=False) -> bytes` | Office or text file mask  |
| `unmask_file(bytes_or_io, ext) -> bytes`        | Office or text file rehydrate        |

### Module-level shorthands

```python
masked   = mask_text("Acme Corp")     # uses a default Sanitizer()
restored = unmask_text(masked)
```

Useful for one-liners and tests; for sustained use, hold a `Sanitizer`
instance.

### Multiple stores in one process

If you need *project-scoped* dictionaries (e.g. per customer), construct
a `Sanitizer` with a custom `db_path`:

```python
acme = Sanitizer(db_path="/var/lib/cpf/acme.db")
beta = Sanitizer(db_path="/var/lib/cpf/beta.db")
```

Each gets its own SQLite + encryption key namespace (the master key still
comes from the keyring, but the lookup HMAC + Fernet token differ per
store — terms don't leak across).

> Caveat: the bundled HTTPS API and Web UI use the *default* singleton.
> If you serve multiple customers from one process you'll need to fork
> `api.py` to take a `Sanitizer` from request context.

---

## 5. The HTTPS API

### Auth

`Authorization: Bearer <token>` on every endpoint except `/v1/health`.
The token is generated on first run (`crypto.get_or_create_api_token()`)
and stored at `<data_dir>/api_token` (mode 0600 on POSIX). Comparison is
constant-time (`hmac.compare_digest`).

### Endpoints

| Method | Path                       | Body / form                          | Response                                |
|--------|----------------------------|--------------------------------------|-----------------------------------------|
| GET    | `/v1/health`               | (no auth)                            | `{"status":"ok","version":"..."}`       |
| POST   | `/v1/mask`                 | `{"text":"...","auto_add":false}`    | `{"masked":"..."}`                      |
| POST   | `/v1/unmask`               | `{"text":"..."}`                     | `{"unmasked":"..."}`                    |
| POST   | `/v1/detect`               | `{"text":"..."}`                     | `{"candidates":["...", ...]}`           |
| POST   | `/v1/mask/file`            | multipart `file`, `ext`, `auto_add`  | binary, `Content-Type` = office mime    |
| POST   | `/v1/unmask/file`          | multipart `file`, `ext`              | binary, `Content-Type` = office mime    |
| GET    | `/v1/dictionary`           | —                                    | `{"entries":[{"id","original_term","token"}]}` |
| POST   | `/v1/dictionary`           | `{"term":"...","token":"opt"}`       | `{"id","original_term","token"}`        |
| DELETE | `/v1/dictionary/<id>`      | —                                    | `204`                                   |
| GET    | `/v1/patterns`             | —                                    | `{"patterns":[{"id","name","regex"}]}`  |
| POST   | `/v1/patterns`             | `{"name":"...","regex":"..."}`       | `201` or `400` on bad regex             |
| DELETE | `/v1/patterns/<id>`        | —                                    | `204`                                   |

### Error contract

All error responses are JSON with shape `{"error": "<message>"}`.

| Code | When                                         |
|------|----------------------------------------------|
| 400  | Missing / invalid field, bad regex           |
| 401  | Missing or invalid bearer token              |
| 404  | Unknown route                                |
| 405  | Wrong method                                 |
| 413  | Request body exceeds `MAX_BODY_BYTES`        |
| 429  | Rate limit exceeded (60 req/min per token)   |
| 500  | Unhandled internal error (no stack leaked)   |

### Hardening headers (every response)

```
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Cache-Control: no-store
Strict-Transport-Security: max-age=63072000
X-Frame-Options: DENY
```

### Tuning knobs

In `doc_sanitizer/api.py`:

```python
DEFAULT_HOST       = "127.0.0.1"
DEFAULT_PORT       = 8443
MAX_BODY_BYTES     = 25 * 1024 * 1024
RATE_LIMIT_PER_MIN = 60
```

Override per-process:
```python
from doc_sanitizer import api
api.MAX_BODY_BYTES = 100 * 1024 * 1024
api.serve(port=8443)
```

Or wire your own Flask app with `api.create_app(sanitizer=…, token=…)`
and run it under your own WSGI server.

---

## 6. Encryption details

### What's encrypted, what isn't

| Field                                | Plaintext on disk? | Why                              |
|--------------------------------------|--------------------|----------------------------------|
| `dictionary.original_term_enc`       | **No**             | The actual secret                |
| `dictionary.token`                   | Yes                | Public substitution target       |
| `dictionary.term_lookup_hash`        | Hashed             | HMAC-SHA256 of `lower(term)`     |
| `dictionary.id` / `created_utc`      | Yes                | Metadata, not secret             |
| `patterns.regex` / `name`            | Yes                | Configuration, not PII           |
| `meta.*`                             | Yes                | Migration flags etc.             |

Cipher: **Fernet** (AES-128-CBC + HMAC-SHA256 in a single composite token,
random IV per record). We do *not* roll our own cipher composition.

### Master key storage

`doc_sanitizer/crypto.py::get_or_create_master_key()` returns the URL-safe
base64 Fernet key. Storage order:

1. **OS keyring** via the `keyring` library
   (Windows Credential Manager, macOS Keychain, Linux Secret Service / kwallet)
2. **File fallback** `<data_dir>/master.key`, mode 0600 on POSIX

If the keyring works once, the file fallback is created only as a
migration backstop. To force file mode, set the env var
`PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring`.

### Lookup hash

```python
term_lookup_hash = HMAC-SHA256(master_key, lower(term)).hexdigest()
```

This lets us:
- de-dup case-insensitively in O(1)
- *not* store plaintext in any index

…without giving a brute-force window: an attacker without the key can't
test "is `Acme Corp` in this DB?" because they can't compute the HMAC.

### Per-row encryption

```python
ciphertext = Fernet(master_key).encrypt(term.encode("utf-8"))
```

`Fernet.encrypt` includes a fresh 128-bit IV and an HMAC tag, so two rows
with the same plaintext produce different ciphertexts.

---

## 7. Adding new built-in patterns

Edit `doc_sanitizer/patterns.py`:

```python
FIXED_PATTERNS: list[tuple[str, str]] = [
    ...
    ("My new pattern", r"\bSKU-\d{6}\b"),
]
```

Keep it minimal — high false-positive patterns degrade `auto_add`. Add a
test in `tests/test_sanitizer.py` to lock the behaviour.

---

## 8. Building binaries

### Locally

```bash
pip install -e ".[build]"
pyinstaller --noconfirm doc_sanitizer.spec
```

Output:

| OS       | Path                          |
|----------|-------------------------------|
| Windows  | `dist/doc-sanitizer.exe`      |
| macOS    | `dist/doc-sanitizer` + `dist/doc-sanitizer.app` |
| Linux    | `dist/doc-sanitizer`          |

The spec file embeds Flask templates and static files via `datas` and
adds keyring backends as `hiddenimports` (PyInstaller can't auto-discover
them).

### CI

`.github/workflows/build.yml`:

| Job   | What it does                                                |
|-------|--------------------------------------------------------------|
| test  | `pytest -q` on `{ubuntu, windows, macos}-latest × py{3.11,3.12}` |
| build windows-exe | PyInstaller on windows-latest, uploads `doc-sanitizer.exe` |
| build macos-app   | PyInstaller on macos-latest, zips and uploads `doc-sanitizer.app.zip` |

A push to a tag `v*` additionally creates / updates a GitHub Release with
both binaries attached (via `softprops/action-gh-release@v2`).

---

## 9. Cutting a release

```bash
# 1. bump the version in pyproject.toml AND doc_sanitizer/__init__.py
# 2. update README "Examples" / DECISIONS if the release changes them
# 3. commit + push
git add pyproject.toml doc_sanitizer/__init__.py README.md DECISIONS.md
git commit -m "Bump to vX.Y.Z"
git push origin main

# 4. tag + push
git tag vX.Y.Z -m "vX.Y.Z — short description"
git push origin vX.Y.Z

# 5. CI builds + uploads — verify on the Releases page
gh release view vX.Y.Z --repo cogniflow-ai/doc-sanitizer
```

If you want to publish a wheel to PyPI later, `pyproject.toml` is already
configured for `setuptools build_meta`; just `python -m build` then
`twine upload dist/*.whl`.

---

## 10. Extension points

### Custom encryption backend

Subclass `SecretStore`, override `_init_schema` if you need a different
shape. The current implementation expects a Fernet-shaped `bytes` token
in `original_term_enc` — if you swap ciphers, also update
`crypto.encrypt` / `crypto.decrypt`.

### Different keyring backend

`keyring` autodetects. To pin a specific backend at install time:

```python
import keyring
from keyring.backends.macOS import Keyring as MacKeyring
keyring.set_keyring(MacKeyring())
```

### Custom patterns store

Patterns are persisted next to the encrypted dictionary. If you want a
different policy (e.g. read-only patterns from a YAML file), pass a custom
`SecretStore` subclass that overrides `get_patterns()` / `add_pattern()`
to read from your source of truth.

### Replace the Web UI

It's a single Flask app in `doc_sanitizer/web.py` that consumes the same
public library API. You can replace it wholesale with your own framework
without touching anything else.

---

## 11. Contributing

1. Fork, branch off `main`, name it `feat/<topic>` or `fix/<topic>`.
2. Write a test first (or alongside) — `tests/test_sanitizer.py` is small
   on purpose, follow the same style.
3. Run `pytest -q` before pushing. If you change `api.py`, also run
   `python clients/https_client_demo.py` against the source tree.
4. Open a PR with the description filled in. The CI matrix gates merge.
5. Squash-merge is the default.

### Coding standards

- Python 3.10+ syntax allowed (`X | None`, `dict[str, Y]`, etc.)
- Type-hint public functions; dunder / private methods may skip hints
- No global mutable state outside the documented singletons
  (`secrets_store._default`, the test client / Flask app)
- Don't add comments that re-state the code — prefer better names. *Why*
  comments are welcome.

### Things we will *not* accept

- Adding bind-anywhere capability to `serve()` (that defeats the security
  story). If you need a remote server, fork and run behind your own VPN /
  reverse proxy.
- Removing the encryption layer to "speed things up". The DB is small;
  encryption overhead is unmeasurable.
- Auto-uploading anything anywhere. CPF is local-first and stays that way.

---

## 12. Performance notes

- `mask_text` is O(N · L) where N is dictionary size and L is text length
  (one regex sub per term). For dictionaries > 1k terms, consider a single
  combined regex with alternation. Patches welcome.
- `extract_text` for `.docx` / `.pptx` is best-effort; embedded objects,
  charts, and macros are ignored. If you need to mask those, swap
  `python-docx` for the lower-level `python-docx-ng` and walk the OOXML
  tree directly.
- The HTTPS API uses Flask's dev server (Werkzeug). Fine for local-only
  single-user use; replace with `waitress` (Windows) or `gunicorn`
  (POSIX) if you find yourself stress-testing it.

---

## 13. Security disclosure

Please **do not** open a public issue for security vulnerabilities.
Instead, email the maintainer (see `cogniflow-ai`'s GitHub profile) with:

1. A description of the vulnerability
2. Reproduction steps
3. Affected version(s)

We aim to acknowledge within 72 hours. Public disclosure is coordinated
once a fix is shipped.

---

## 14. License

MIT — see [`LICENSE`](../LICENSE).
