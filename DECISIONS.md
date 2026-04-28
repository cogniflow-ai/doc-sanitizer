# Decisions Log

Captures the non-obvious choices made while hardening the tool, adding the
HTTPS API, and packaging it for distribution. Review and override anything you
disagree with — the relevant code lives in `doc_sanitizer/` and is small.

## 1. SQLite hardening — column-level Fernet, not SQLCipher

**Decision:** Encrypt sensitive columns with Fernet (AES-128-CBC + HMAC-SHA256
in a single composite token, from the `cryptography` package). Store the
master key in the OS keyring (`keyring` package) with a file-backed fallback
at `<data_dir>/master.key` (chmod 0600 on POSIX).

**Why not SQLCipher:**
- `pysqlcipher3` requires a SQLCipher build at install time — fragile on
  Windows and incompatible with PyInstaller bundling.
- We only need to protect `original_term`. The `token` column is opaque by
  design (`__TERM_42__`), so leaving it plaintext is intentional and lets us
  do substitution without per-row decryption on every mask/unmask call.

**Trade-off:** Anyone with read access to the DB sees row counts, token IDs,
and timestamps — but never the original terms. Acceptable for a single-user
local tool.

## 2. Term lookup uses HMAC, not plaintext or random salt

`term_lookup_hash = HMAC-SHA256(master_key, lower(term))`. This lets us
de-duplicate case-insensitively without decrypting every row on every insert,
and an attacker without the master key cannot brute-force candidate terms
offline (they would need the key first). Tokens are also stored in plaintext
because they need to be substituted into output text — they are not secrets.

## 3. Migration of the existing legacy `sanitiser.db`

The legacy plaintext DB is migrated transparently on first run. The original
file is renamed to `sanitiser.db.legacy.bak` so you can verify, then **you
should delete the backup manually** — it still contains plaintext secrets.

The `.gitignore` excludes both files; they will not be committed.

## 4. HTTPS API — Flask + self-signed cert, loopback only

- **Bind:** Hard-refuses any host that isn't 127.0.0.1, ::1, or localhost.
- **TLS:** Self-signed RSA-2048 cert, valid 5 years, auto-generated on first
  run under `<data_dir>/tls/`. SAN includes localhost, 127.0.0.1, ::1.
- **Auth:** Bearer token (`secrets.token_urlsafe(32)`), constant-time
  comparison. Token printed once and stored at `<data_dir>/api_token` (0600).
- **Rate limit:** 60 req/min per token, in-memory deque per token-prefix.
- **Body cap:** 25 MiB.
- **Hardening headers:** `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  no-referrer`, `Cache-Control: no-store`, HSTS, `X-Frame-Options: DENY`.

**Not implemented (out of scope for a local tool):**
- mTLS / client certificates
- OIDC / SSO
- Audit log to disk
- API key rotation UI (rotate by deleting `api_token` and restarting)

## 5. Library API surface

```python
from doc_sanitizer import Sanitizer, mask_text, unmask_text, mask_file, unmask_file

s = Sanitizer()                   # uses default encrypted DB
s = Sanitizer(db_path="...")      # custom DB path (e.g. project-scoped)
s.mask_text(text, auto_add=False) # add candidates first if auto_add=True
s.mask_file(bytes_, ext=".docx")
s.unmask_*(...)
s.dictionary() / s.add_term() / s.remove_term() / s.export_dictionary() / s.import_dictionary()
s.patterns() / s.add_pattern() / s.remove_pattern()
s.detect(text) / s.detect_in_file(bytes_, ext)
```

The Flask UI and HTTPS API are both consumers of this library — no business
logic lives in the route handlers anymore.

## 6. macOS `.app` build

This codebase was developed on Windows. A `.app` bundle cannot be built from
Windows. The decision was therefore:

- A PyInstaller spec (`doc_sanitizer.spec`) builds a single-file binary on
  whichever OS runs it.
- A GitHub Actions workflow (`.github/workflows/build.yml`) runs PyInstaller
  on `windows-latest` AND `macos-latest` for every push to `main`, attaching
  both artifacts to the workflow run. Tagged releases (`v*`) also publish to
  GitHub Releases.

To produce `.app` locally, run on a Mac:
```bash
pip install -e ".[build]"
pyinstaller doc_sanitizer.spec
```

## 7. Path resolution

Per-OS user data dir, override-able via `DOC_SANITIZER_HOME`:
- Windows: `%LOCALAPPDATA%\doc-sanitizer\`
- macOS:   `~/Library/Application Support/doc-sanitizer/`
- Linux:   `$XDG_DATA_HOME/doc-sanitizer/` or `~/.local/share/doc-sanitizer/`

The data dir is created with `mode=0o700` on POSIX. On Windows we deliberately
do **not** call `icacls` to tighten ACLs further — an earlier attempt did so
with `icacls /inheritance:r /grant:r USER:(R,W)`, which removed `DELETE`
permission and prevented SQLite from opening its own database on subsequent
runs. The default %LOCALAPPDATA% inherited ACLs are already user-scoped.

## 8. Top-level shims

The original `app.py`, `db.py`, `extractor.py`, `obfuscator.py`, `patterns.py`
files at the project root are now thin shims that re-export from the
`doc_sanitizer` package. Existing scripts importing `import db` or
`from obfuscator import …` keep working unchanged.

## 9. Repository visibility

**Public** at the user's request (initially created private as a precaution).
The release binaries are unsigned but contain no embedded secrets — the master
key, API token, and self-signed cert are all generated at first run on the
end-user's machine. No state files are committed; `.gitignore` excludes
`*.db*`, `master.key`, `api_token`, `tls/`, and the legacy `sanitiser.db.legacy.bak`.

## 10. Things explicitly NOT done

- **No backwards compatibility for the unencrypted DB schema.** The new
  `dictionary` table has different columns (`original_term_enc`, `term_lookup_hash`).
  Reading the old schema directly is no longer supported; only the one-shot
  migration path is.
- **No multi-user auth.** This remains a single-user tool. The bearer token
  is one shared secret.
- **No CSRF protection on the Flask UI.** The UI binds to 127.0.0.1 and is
  intended for single-user use; CSRF is out of scope.
- **No audit logging.** Add structured logging via the standard Flask logger
  if you need it; the API factory leaves the logger configurable.
- **No code signing on the `.exe` / `.app`.** Users on Windows will see a
  SmartScreen warning until you sign with a certificate; on macOS the
  unsigned `.app` will require right-click → Open the first time.

## Open follow-ups

If anything below matters for your use case, file an issue and I'll wire it up:

- [ ] Switch from Flask dev server to `waitress` (Windows) / `gunicorn` (POSIX)
      for better-tested HTTPS handling at higher request rates.
- [ ] Add OpenAPI 3.1 spec generation (e.g. via `apispec`) so external clients
      can codegen.
- [ ] Optional master-passphrase mode that re-derives the master key with
      Argon2id at startup, so the key is never persisted unencrypted.
- [ ] Code-signing & notarization workflows for the macOS `.app`.
