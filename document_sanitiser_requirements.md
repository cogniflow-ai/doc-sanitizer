# Document Sanitiser — Requirements

## Purpose
A single-user personal tool to sanitise documents before submission to an LLM and
rehydrate them afterwards. Supports obfuscation of sensitive terms via a persistent
dictionary and regex-based detection.

---

## Architecture

### Architecture
A single-process, server-side rendered monolith. No frontend build step, no bundler,
no API layer. The server renders complete HTML pages and HTML fragments. The client
does no data processing. Single-user personal tool — no authentication, no sessions.

### Backend
- **Language**: Python 3.11+
- **Framework**: Flask — all routes return either a full Jinja2-rendered HTML page
  or a partial HTML fragment (for HTMX requests)
- **Database**: SQLite via the Python standard library `sqlite3` module — no ORM,
  plain SQL queries
- **State**: a single in-memory Python dict holding the current file name, extracted
  text, and sanitised text. Reset when the user starts a new job. No session
  management, no cookies, no temp directories.
- **Office file processing**: `python-docx` for `.docx`, `python-pptx` for `.pptx`,
  `openpyxl` for `.xlsx` — extraction and in-place token substitution for rehydration
- **All other file types**: read and written as plain text regardless of extension

### Frontend
- **Templating**: Jinja2 — rendered server-side by Flask using `render_template`
- **Interactivity**: HTMX (loaded from CDN) — used for partial page updates only
  (inline regex validation, search and highlight in REQ11). All other interactions
  are standard form submissions with full page reload.
- **Styling**: Plain CSS in a single `static/style.css` file — no CSS framework,
  no preprocessor
- **No JavaScript** is written by hand. All interactivity is handled by HTMX
  attributes in HTML.

---

## Functional Requirements

### REQ1 — File Upload
The user uploads a single file per session. `.docx`, `.pptx`, and `.xlsx` files use
format-specific processing. All other file types (`.txt`, `.md`, `.py`, `.js`, `.ts`,
`.json`, `.yaml`, `.csv`, and any other text-based extension) are read and written as
plain text.

### REQ2 — Text Extraction
The application extracts plain text from the uploaded file using format-specific
libraries (`python-docx`, `python-pptx`, `openpyxl`) for Office formats. For all
other types, the file is read as plain text. Extraction is best-effort; embedded
objects, charts, and macros in Office files are ignored.

### REQ3 — Sensitive Term Detection
The application scans extracted text using two layers:
- **Fixed patterns** (always active): emails, UUIDs, numbers, capitalised multi-word
  sequences, alphanumeric ID shapes.
- **User-defined patterns**: stored in SQLite, applied alongside fixed patterns.
  Validated via Python's `re` module; compilation errors are shown inline via HTMX.

All matching is **case-insensitive**. The user reviews all flagged terms and confirms
or dismisses each one. Before confirming, the user can edit the term to set the exact
canonical form that will be stored in the dictionary and restored on rehydration.

### REQ4 — Global Dictionary
The application maintains a persistent SQLite dictionary of `original_term → token`
pairs (e.g. `Acme Corp → __ORG_1__`). The stored form of each term is the canonical
form restored on rehydration. The user can view, manually add, and delete entries at
any time via a simple table UI.

### REQ5 — Obfuscation
The application replaces all dictionary terms in the extracted text with their tokens,
producing sanitised text. Matching is case-insensitive. Rehydration always restores
the canonical stored form verbatim. The sanitised text can be copied or downloaded
as `.txt`.

### REQ6 — Rehydration (plain text)
The user pastes or uploads LLM-processed plain text containing tokens. The application
reverses the substitution using the dictionary and offers the restored text for
download as `.txt`.

### REQ7 — Rehydration (file formats)
The user uploads an LLM-produced file of any supported format containing tokens. The
application performs plain in-place token substitution throughout the file and returns
the rehydrated file for download in the same format. For `.docx`, `.pptx`, and `.xlsx`
files, format-specific libraries are used. All other file types are treated as plain
text.

### REQ8 — Dictionary Import / Export
The user can export the full dictionary as a `.json` file and re-import it. This
allows the same dictionary to be reused across jobs.

### REQ9 — Single Global State
There are no sessions. The application holds one single in-memory state: the current
file name, extracted text, and sanitised text. Starting a new job resets this state.
The dictionary and user-defined regex patterns are persistent across jobs.

### REQ10 — Single-Page Workflow
The UI guides the user through a linear flow:

**Upload → Detect & Review → Obfuscate → (external LLM step) → Rehydrate → Download**

All steps are accessible from one page using HTMX partial updates.

### REQ11 — Post-Obfuscation Review and Re-obfuscation
After obfuscation, the user can search the sanitised text within the tool. Matches
are highlighted. A single action adds a matched term to the dictionary. The user can
also update patterns or dictionary entries and re-run obfuscation against the
already-extracted text without re-uploading the file.

---

## Data Model (SQLite)

### table: dictionary
| column        | type    | notes                          |
|---------------|---------|--------------------------------|
| id            | INTEGER | primary key, autoincrement     |
| original_term | TEXT    | canonical form, unique         |
| token         | TEXT    | e.g. `__ORG_1__`, unique       |

### table: patterns
| column      | type    | notes                             |
|-------------|---------|-----------------------------------|
| id          | INTEGER | primary key, autoincrement        |
| name        | TEXT    | human-readable label              |
| regex       | TEXT    | validated Python regex expression |

---

## Dependencies

| package      | purpose                        |
|--------------|--------------------------------|
| flask        | web framework                  |
| jinja2       | server-side templating         |
| python-docx  | `.docx` extraction & write-back |
| python-pptx  | `.pptx` extraction & write-back |
| openpyxl     | `.xlsx` extraction & write-back |

HTMX is loaded from CDN — no local installation required.
