# Cogniflow Privacy Filter — User Guide

Cogniflow Privacy Filter (CPF) is a **local-first** tool that masks sensitive
information in your documents before you send them to an external Large
Language Model (ChatGPT, Claude, Gemini, …) and rehydrates the LLM's reply
back into the originals.

It runs entirely on your machine. Your secrets never leave the device.

This guide is for *end users* — people who want to install it and start
masking documents. If you're a developer who wants to embed CPF in your
own application, see [`developer-guide.md`](./developer-guide.md).

---

## What it does

```
                                                   ┌──────────────┐
   your.docx     ─►  Cogniflow Privacy Filter  ─►  │ external LLM │
   (with PII)        (masks Acme→__TERM_5__)       │ (ChatGPT...) │
                                                   └──────┬───────┘
                                                          │
   your.docx     ◄─  Cogniflow Privacy Filter  ◄──────────┘
   (rehydrated)      (unmasks __TERM_5__→Acme)
```

It supports `.docx`, `.pptx`, `.xlsx`, plain text, Markdown, and any
text-based file. The mapping (e.g. `Acme Corp ↔ __TERM_5__`) is stored
**encrypted at rest** in a per-user SQLite database.

---

## Three ways to use it

| Mode        | When to pick it                                                     |
|-------------|----------------------------------------------------------------------|
| **Web UI**  | You want a browser-based GUI, click-through workflow, no terminal.  |
| **CLI**     | You want one-shot command-line operations on individual files.      |
| **HTTPS API** | You want to integrate with another local app (any language).      |

You can mix-and-match: the same encrypted dictionary is shared across all
three.

---

## 1. Install

### 1.1 Download a pre-built binary (recommended)

Pre-built `.exe` (Windows) and `.app` (macOS) live on the GitHub Releases
page:

> **https://github.com/cogniflow-ai/doc-sanitizer/releases**

Click the latest release (e.g. `v0.2.0`) and download the right asset:

| OS          | Asset                       |
|-------------|-----------------------------|
| Windows 10/11 | `doc-sanitizer.exe`       |
| macOS 11+   | `doc-sanitizer.app.zip`     |

#### Windows

1. Download `doc-sanitizer.exe` (≈ 33 MB).
2. (Optional) Move it to a permanent location, e.g. `C:\Tools\doc-sanitizer.exe`.
3. The first time you run it, **SmartScreen will warn you** ("Windows
   protected your PC"). The binary is unsigned. If you trust the source:
   - Click **More info** → **Run anyway**.
4. Open a Command Prompt or PowerShell:
   ```cmd
   C:\Tools\doc-sanitizer.exe version
   ```
   Expected output: `0.2.0`.

#### macOS

1. Download `doc-sanitizer.app.zip` (≈ 30 MB).
2. Unzip → you get `doc-sanitizer.app`.
3. Move it to `/Applications` if you like.
4. The first time you double-click it, macOS will refuse to launch it
   (Gatekeeper, unsigned app). Workaround:
   - **Right-click** `doc-sanitizer.app` → **Open**
   - Click **Open** in the confirmation dialog
   - Subsequent launches are unblocked.

#### Linux / "I want to run from source"

There are no pre-built Linux binaries yet — see *Install from source* below.

### 1.2 Install from source

Requires Python 3.10+.

```bash
git clone https://github.com/cogniflow-ai/doc-sanitizer.git
cd doc-sanitizer
python -m venv venv
source venv/bin/activate              # macOS/Linux
# or: venv\Scripts\activate           # Windows

pip install -e .
doc-sanitizer version
```

---

## 2. First run

The first time you launch CPF (in any of the three modes) it does two
one-time setups:

1. **Generates a master encryption key** for the secrets DB. Stored either
   in your OS keyring (Windows Credential Manager, macOS Keychain) or in a
   file `master.key` inside the data dir (file mode 0600 on Linux/macOS).
2. **Generates a self-signed TLS certificate** for the local HTTPS API.

You'll see lines like:

```
[doc-sanitizer] HTTPS API listening on https://127.0.0.1:8443
[doc-sanitizer] data dir : /Users/you/Library/Application Support/doc-sanitizer
[doc-sanitizer] cert     : .../tls/server.crt
[doc-sanitizer] token    : .../api_token (chmod 600)
[doc-sanitizer] auth     : Authorization: Bearer abcdefghijklmnopqrstuvwxyz...
```

> ⚠️ **Save the master key.** If you lose it, the encrypted dictionary
> cannot be decrypted. See *Backup & recovery* below.

---

## 3. Use the Web UI

```bash
doc-sanitizer ui
```

Open http://127.0.0.1:5001 in your browser. The flow is:

1. **Upload** your file (`.docx`, `.pptx`, `.xlsx`, `.txt`, `.md`, …).
2. **Review candidates** — CPF auto-detects emails, names, IDs, phones,
   etc. Click ✓ to add a candidate to the dictionary, ✗ to dismiss it.
   You can also edit the candidate before adding (e.g. canonicalize
   "ACME corp" → "Acme Corp").
3. **Obfuscate** — the file is masked using your dictionary. Download the
   masked file or copy the text.
4. *(External step)* Paste the masked text into ChatGPT / Claude / Gemini.
5. **Rehydrate** — paste the LLM's reply back, or upload the LLM-edited
   `.docx`/`.pptx`/`.xlsx`. CPF restores the originals.
6. **Download** the rehydrated file.

The dictionary persists across sessions — you only need to add a term once.

### Manage your dictionary

Same page, **Dictionary** section:
- Add terms manually
- Delete entries
- **Export** the dictionary to JSON (encrypted master key NOT included)
- **Import** a previously-exported JSON

### Manage detection patterns

**Patterns** section: add custom regular expressions to extend the auto-
detection. Examples:
- `\bORDER-\d{6}\b`  → match `ORDER-123456`-style refs
- `\bSKU\d{4,}\b`    → match SKU codes

Invalid regex shows an inline error.

---

## 4. Use the command line

```bash
doc-sanitizer mask  report.docx       # → report.masked.docx
doc-sanitizer unmask report.docx      # → report.unmasked.docx
doc-sanitizer paths                    # show where state lives
doc-sanitizer token                    # show the API bearer token
doc-sanitizer version                  # show the version
```

The `--auto-add` flag tells `mask` to auto-detect and add candidates
before masking. **Use it carefully** — auto-detected terms may overlap
unexpectedly (e.g. `ORD` matches inside `order`). For predictable
round-trips, add terms via the UI or programmatically before masking.

---

## 5. Use the HTTPS API

Start the API in one terminal:

```bash
doc-sanitizer api
# → https://127.0.0.1:8443
```

In another terminal, get the token and the cert path:

```bash
TOKEN=$(doc-sanitizer token)
CERT="$(doc-sanitizer paths | awk -F': ' '/tls dir/ {print $2}')/server.crt"
```

### Mask plain text

```bash
curl --cacert "$CERT" -X POST \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"text": "Mario Rossi at Acme Corp"}' \
     https://127.0.0.1:8443/v1/mask
```

Response:
```json
{"masked": "__TERM_2__ at __TERM_1__"}
```

### Unmask plain text

```bash
curl --cacert "$CERT" -X POST \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"text": "__TERM_2__ at __TERM_1__"}' \
     https://127.0.0.1:8443/v1/unmask
```

### Mask a `.docx`

```bash
curl --cacert "$CERT" -X POST \
     -H "Authorization: Bearer $TOKEN" \
     -F "file=@report.docx" \
     -F "ext=.docx" \
     -o report.masked.docx \
     https://127.0.0.1:8443/v1/mask/file
```

### Add a term

```bash
curl --cacert "$CERT" -X POST \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"term": "Acme Corporation"}' \
     https://127.0.0.1:8443/v1/dictionary
```

For the full list of endpoints, see [`developer-guide.md`](./developer-guide.md#api-endpoints).

---

## 6. Where state lives

| OS       | Path                                                  |
|----------|-------------------------------------------------------|
| Windows  | `%LOCALAPPDATA%\doc-sanitizer\`                       |
| macOS    | `~/Library/Application Support/doc-sanitizer/`        |
| Linux    | `$XDG_DATA_HOME/doc-sanitizer/` or `~/.local/share/doc-sanitizer/` |

Inside that folder:

```
sanitizer.db        — encrypted SQLite store (your dictionary + patterns)
master.key          — file fallback for the encryption key (0600)
api_token           — HTTPS API bearer token (0600)
tls/server.crt      — self-signed certificate
tls/server.key      — TLS private key (0600)
```

You can override the location with the environment variable
`DOC_SANITIZER_HOME=/path/to/folder`.

---

## 7. Backup & recovery

### What to back up

The single most important file is the **master encryption key**.

If `keyring` is available:
- The key sits in your OS keyring under service `doc-sanitizer`,
  user `master-key`. **It is included in your normal keychain backup**
  (Windows Credential Manager export, macOS Keychain Access).

If `keyring` is *not* available (rare, e.g. headless Linux without DBus):
- The key lives at `<data_dir>/master.key`. **Back this file up**
  alongside `sanitizer.db`. Without it, the DB is unreadable.

### Restore on a new machine

1. Install Cogniflow Privacy Filter on the new machine.
2. Run `doc-sanitizer paths` to see where state will live.
3. Copy `sanitizer.db` and `master.key` (if present) into that directory.
4. Or: restore the `master-key` entry into the keyring before launching CPF.

### Export your dictionary as portable JSON

The dictionary itself can be exported to JSON (still containing the
plaintext terms — handle with care):

- **Web UI** → Dictionary → **Export**
- **API** → `GET /v1/dictionary` → save the JSON

To re-import on a fresh install:
- **Web UI** → Dictionary → **Import**
- **API** → `POST /v1/dictionary` for each term (or use the UI's import
  endpoint at `POST /dictionary/import`)

---

## 8. Security expectations

| What CPF does                                     | What CPF does NOT do |
|---------------------------------------------------|----------------------|
| Encrypts the term-to-token dictionary at rest     | Encrypt the *file* you upload — only the dictionary |
| Binds servers to `127.0.0.1` only                 | Provide multi-user access control |
| Rate-limits the HTTPS API to 60 req/min per token | Replace a hosted enterprise DLP solution |
| Auto-generates self-signed TLS                    | Validate certs against a public CA |
| Refuses bodies > 25 MiB                           | Stream large files |
| Constant-time bearer-token compare                | Hash secrets with a passphrase by default *(see §10)* |

If your security model needs anything in the right column, see
[`developer-guide.md`](./developer-guide.md) for extension hooks.

---

## 9. Troubleshooting

### "I see a SmartScreen warning when I run the .exe"

Expected — the binary is unsigned. Click **More info → Run anyway**, or
sign it yourself.

### "macOS says the app is damaged"

```bash
xattr -d com.apple.quarantine /Applications/doc-sanitizer.app
```

### "I forgot the master key"

Stop. Do you really need to recover the existing DB, or is wiping and
starting over acceptable?

- **Acceptable:** delete `sanitizer.db` and `master.key`; re-launch CPF.
  A new key is generated and an empty DB is created.
- **Not acceptable:** unfortunately the encrypted dictionary cannot be
  recovered. The encryption is genuine.

### "Port 5001 / 8443 is already in use"

```bash
doc-sanitizer ui  --port 5005
doc-sanitizer api --port 9443
```

### "Windows: SQLite says 'unable to open database file'"

Almost always caused by a third-party tool over-tightening NTFS ACLs on
`%LOCALAPPDATA%\doc-sanitizer\`. Reset:
```cmd
icacls %LOCALAPPDATA%\doc-sanitizer /reset /T /Q
```

### "OPF (privacy-filter) installation fails on Windows"

`privacy-filter` depends on `transformers` + `tokenizers` + `torch`.
The wheel for `tokenizers` requires Visual C++ runtime; install the
Microsoft Build Tools 2022 if pip can't find pre-built wheels.

### "I want to talk to the API from a different language"

It's plain HTTPS + JSON / multipart. Any language with an HTTPS client
works. The example in `clients/https_client_demo.py` uses only Python's
stdlib.

---

## 10. Frequently asked questions

**Q: Is my data sent to the cloud at any point?**
A: No. Cogniflow Privacy Filter is 100% local. The HTTPS API binds only
to 127.0.0.1 and refuses any other host. Telemetry is not collected.

**Q: Can multiple people share the same dictionary?**
A: Not designed for that today. The bearer token is one shared secret;
the master key is single-user. Export to JSON and re-import on the other
machine if you need to share term mappings.

**Q: Does CPF detect every form of PII?**
A: No — the built-in regex patterns cover common shapes (emails, phones,
fiscal codes, IBANs, etc.). For ML-grade detection, layer it with the
[OpenAI Privacy Filter](https://github.com/openai/privacy-filter)
demonstrated in `examples/openai-privacy-filter/`.

**Q: Why are the binaries unsigned?**
A: Signing requires a paid certificate (Windows: ~$80–300/yr; macOS
Apple Developer: $99/yr). Tracked as a follow-up; sign locally if you
need to distribute internally.

**Q: How do I uninstall?**
A: Delete the binary (Windows) or the `.app` (macOS), and delete the
data directory (see §6). On macOS also run:
```bash
security delete-generic-password -s doc-sanitizer
```
to clear the keyring entry.

---

## 11. Where to file issues

https://github.com/cogniflow-ai/doc-sanitizer/issues

When reporting a bug please include:
- OS + version
- Python version (`python --version`)
- Output of `doc-sanitizer version` and `doc-sanitizer paths`
- Exact command and full output (redact any real PII)

---

## 12. License

MIT — see [`LICENSE`](../LICENSE).
