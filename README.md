# doc-sanitizer

A local-first tool for masking sensitive terms in documents (`.docx`, `.pptx`,
`.xlsx`, plain text) before sending them to an external LLM, and rehydrating
the LLM's output back to the original terms.

Three usage modes:

1. **Web UI** — local Flask app at `http://127.0.0.1:5001` (single-user).
2. **HTTPS API** — local masking-as-a-service at `https://127.0.0.1:8443` for
   other apps on the same machine.
3. **Python library** — `from doc_sanitizer import Sanitizer`.

All three share the same encrypted SQLite secrets store.

---

## Install

```bash
pip install -e .
```

or for development:

```bash
pip install -r requirements.txt
```

## Quick start

### Web UI
```bash
doc-sanitizer ui
# → http://127.0.0.1:5001
```

### HTTPS API
```bash
doc-sanitizer api
# → https://127.0.0.1:8443
# bearer token printed on first run, also via:  doc-sanitizer token
```

Example client call:
```bash
TOKEN=$(doc-sanitizer token)
curl -k -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"text": "Mario Rossi @ Acme Corp", "auto_add": true}' \
     https://127.0.0.1:8443/v1/mask
```

### Library
```python
from doc_sanitizer import Sanitizer

s = Sanitizer()
s.add_term("Acme Corp")
masked = s.mask_text("Acme Corp ships widgets")    # "__TERM_1__ ships widgets"
restored = s.unmask_text(masked)                   # "Acme Corp ships widgets"

# Office files (bytes in / bytes out)
masked_bytes = s.mask_file(open("doc.docx", "rb").read(), ext=".docx")
```

### CLI one-shots
```bash
doc-sanitizer mask  report.docx     # writes report.masked.docx
doc-sanitizer unmask report.docx    # writes report.unmasked.docx
doc-sanitizer paths                 # show where state lives
```

---

## Security model

**This is a single-user, local-only tool.** All servers bind to `127.0.0.1` by
default; binding to a non-loopback address is rejected.

| Concern                         | Mitigation                                                                         |
|---------------------------------|------------------------------------------------------------------------------------|
| Sensitive term storage          | Encrypted-at-rest with Fernet (AES-128-CBC + HMAC-SHA256)                          |
| Master key storage              | OS keyring (Windows Credential Manager / macOS Keychain) with file fallback (0600) |
| Term lookup without decryption  | HMAC-SHA256 of `lower(term)` keyed by master key                                   |
| API authentication              | Bearer token (`secrets.token_urlsafe(32)`), constant-time compare                  |
| API transport                   | Self-signed TLS cert, RSA-2048, auto-generated, valid 5 years                      |
| External access                 | Refused — server binds 127.0.0.1 only                                              |
| Body size DoS                   | 25 MiB request cap                                                                 |
| Per-token rate limit            | 60 requests / minute                                                               |
| Hardening headers               | nosniff, no-referrer, no-store, HSTS, X-Frame-Options=DENY                         |

State lives under (in priority order):

| OS       | Location                                              |
|----------|-------------------------------------------------------|
| Windows  | `%LOCALAPPDATA%\doc-sanitizer\`                       |
| macOS    | `~/Library/Application Support/doc-sanitizer/`        |
| Linux    | `$XDG_DATA_HOME/doc-sanitizer/` or `~/.local/share/…` |

Override with `DOC_SANITIZER_HOME=/path` (useful for tests / portable runs).

### Key recovery

The master key is the **only** thing standing between you and your masked
secrets. If you lose it, the encrypted dictionary is unrecoverable.

If `keyring` is available, the key sits under service `doc-sanitizer`, user
`master-key`. Otherwise it lives in `master.key` inside the data dir — back
that file up.

---

## Building executables

```bash
pip install -e ".[build]"
pyinstaller doc_sanitizer.spec
# → dist/doc-sanitizer.exe   (Windows)
# → dist/doc-sanitizer.app   (macOS)
```

CI builds for both Windows and macOS run automatically on push via
`.github/workflows/build.yml`.

---

## API endpoints

| Method | Path                       | Body                                 |
|--------|----------------------------|--------------------------------------|
| GET    | /v1/health                 | (no auth)                            |
| POST   | /v1/mask                   | `{"text": "...", "auto_add": false}` |
| POST   | /v1/unmask                 | `{"text": "..."}`                    |
| POST   | /v1/detect                 | `{"text": "..."}`                    |
| POST   | /v1/mask/file              | multipart `file=@x.docx`             |
| POST   | /v1/unmask/file            | multipart `file=@x.docx`             |
| GET    | /v1/dictionary             | —                                    |
| POST   | /v1/dictionary             | `{"term": "..."}`                    |
| DELETE | /v1/dictionary/<id>        | —                                    |
| GET    | /v1/patterns               | —                                    |
| POST   | /v1/patterns               | `{"name": "...", "regex": "..."}`    |
| DELETE | /v1/patterns/<id>          | —                                    |

All except `/v1/health` require `Authorization: Bearer <token>`.

---

## Documentation

| Audience       | Doc                                          |
|----------------|----------------------------------------------|
| End users      | [`docs/user-guide.md`](docs/user-guide.md)         |
| Developers     | [`docs/developer-guide.md`](docs/developer-guide.md) |
| Design notes   | [`DECISIONS.md`](DECISIONS.md)                |

---

## Examples

| Path                                              | What                                                                  |
|---------------------------------------------------|------------------------------------------------------------------------|
| `clients/library_client_demo.py`                  | In-process `Sanitizer` round-trip on `.md` and `.docx`.               |
| `clients/https_client_demo.py`                    | End-to-end HTTPS API round-trip; auto-spawns the API server.          |
| `examples/openai-privacy-filter/opf_demo.py`      | Three OPF use cases incl. **OPF + doc-sanitizer** integration pattern. |

---

## Migration from the old plaintext DB

If `sanitiser.db` (legacy plaintext) is present in the working directory
when the new code first runs, its contents are migrated into the encrypted
store and the file is renamed to `sanitiser.db.legacy.bak`. **Delete the
legacy backup once verified** — it still contains plaintext secrets.

---

## Development

```bash
pip install -e ".[test]"
pytest
```

## License

MIT — see `LICENSE`.
