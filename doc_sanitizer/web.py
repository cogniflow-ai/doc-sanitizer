"""
Flask web UI — single-user local tool.

Mirrors the original `app.py` flow but consumes the `doc_sanitizer` library
(encrypted store + Sanitizer) under the hood. Bound to 127.0.0.1 by default.
"""
from __future__ import annotations

import html as html_lib
import io
import json
import re
from pathlib import Path

from flask import Flask, render_template, request, send_file, redirect, url_for

from doc_sanitizer import extractor
from doc_sanitizer.sanitizer import Sanitizer

try:
    import tkinter as tk
    from tkinter import filedialog
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False


def create_app(sanitizer: Sanitizer | None = None) -> Flask:
    sanitizer = sanitizer or Sanitizer()
    pkg_dir = Path(__file__).resolve().parent
    app = Flask(__name__,
                template_folder=str(pkg_dir / "templates"),
                static_folder=str(pkg_dir / "static"))

    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MiB upload cap

    state = {
        "filename": None,
        "extension": None,
        "original_bytes": None,
        "original_text": None,
        "sanitised_text": None,
        "sanitised_bytes": None,
        "candidates": [],
        "rehydrated_bytes": None,
        "rehydrated_ext": None,
    }

    def reset_state():
        for k in state:
            state[k] = [] if k == "candidates" else None

    def err(msg: str) -> str:
        return f'<p class="error">⚠ {html_lib.escape(msg)}</p>'

    @app.after_request
    def _harden(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    # ── pages ──────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template(
            "index.html",
            state=state,
            dictionary=sanitizer.dictionary(),
            patterns=sanitizer.patterns(),
        )

    @app.post("/reset")
    def reset():
        reset_state()
        return redirect(url_for("index"))

    # ── upload & detect ────────────────────────────────────────────────────
    @app.post("/upload")
    def upload():
        file = request.files.get("file")
        if not file or not file.filename:
            return err("No file selected.")
        filename = file.filename
        ext = Path(filename).suffix.lower()
        file_bytes = file.read()

        reset_state()
        state["filename"] = filename
        state["extension"] = ext
        state["original_bytes"] = file_bytes

        try:
            text = extractor.extract_text(io.BytesIO(file_bytes), ext)
        except Exception as e:
            return err(f"Extraction failed: {e}")

        state["original_text"] = text
        raw = sanitizer.detect(text)
        existing_lower = {e["original_term"].lower() for e in sanitizer.dictionary()}
        seen, candidates = set(), []
        for c in raw:
            cl = c.lower()
            if cl not in existing_lower and cl not in seen:
                seen.add(cl)
                candidates.append(c)
        state["candidates"] = candidates
        return render_template("partials/candidates.html",
                               candidates=candidates, filename=filename)

    @app.post("/detect/confirm")
    def detect_confirm():
        original = request.form.get("original", "").strip()
        term = request.form.get("term", "").strip()
        if term:
            sanitizer.add_term(term)
        state["candidates"] = [c for c in state["candidates"] if c != original]
        return render_template("partials/candidates.html",
                               candidates=state["candidates"],
                               filename=state["filename"])

    @app.post("/detect/dismiss")
    def detect_dismiss():
        original = request.form.get("original", "").strip()
        state["candidates"] = [c for c in state["candidates"] if c != original]
        return render_template("partials/candidates.html",
                               candidates=state["candidates"],
                               filename=state["filename"])

    # ── obfuscate ──────────────────────────────────────────────────────────
    @app.post("/obfuscate")
    def do_obfuscate():
        if not state.get("original_text"):
            return err("No text loaded. Upload a file first.")
        sanitised = sanitizer.mask_text(state["original_text"])
        state["sanitised_text"] = sanitised
        ext = state.get("extension", "")
        state["sanitised_bytes"] = None
        if ext in extractor.OFFICE_EXTS and state.get("original_bytes"):
            try:
                state["sanitised_bytes"] = sanitizer.mask_file(state["original_bytes"], ext)
            except Exception:
                pass
        return render_template("partials/obfuscated.html",
                               highlighted_text=html_lib.escape(sanitised),
                               source_ext=ext,
                               source_filename=state.get("filename", ""))

    @app.get("/download/sanitised")
    def download_sanitised():
        ext = state.get("extension", ".txt")
        if ext in extractor.OFFICE_EXTS and state.get("sanitised_bytes"):
            mime_map = {
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
            stem = Path(state.get("filename", "sanitised")).stem
            buf = io.BytesIO(state["sanitised_bytes"])
            return send_file(buf, mimetype=mime_map[ext], as_attachment=True,
                             download_name=f"{stem}_sanitised{ext}")
        text = state.get("sanitised_text")
        if not text:
            return "Nothing to download", 404
        return send_file(io.BytesIO(text.encode("utf-8")), mimetype="text/plain",
                         as_attachment=True, download_name="sanitised.txt")

    @app.post("/browse/directory")
    def browse_directory():
        if not TKINTER_AVAILABLE:
            return err("tkinter is not available; please type the path manually.")
        try:
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes("-topmost", True)
            selected = filedialog.askdirectory(title="Select destination directory")
            root.destroy()
        except Exception as e:
            return err(f"Could not open directory picker: {e}")
        if not selected:
            return '<span class="hint">No directory selected.</span>'
        path = selected.replace("\\", "/")
        return (f'<script>document.getElementById("save-dir").value = '
                f'{json.dumps(path)};</script>'
                f'<span class="hint" style="color:var(--success)">✓ '
                f'{html_lib.escape(path)}</span>')

    @app.post("/save/sanitised")
    def save_sanitised():
        ext = state.get("extension", ".txt")
        has_binary = ext in extractor.OFFICE_EXTS and state.get("sanitised_bytes")
        if not has_binary and not state.get("sanitised_text"):
            return err("Nothing to save — run obfuscation first.")
        directory = request.form.get("directory", "").strip()
        stem = Path(state.get("filename", "sanitised")).stem
        default_name = f"{stem}_sanitised{ext}" if has_binary else "sanitised.txt"
        filename = request.form.get("save_filename", "").strip() or default_name
        if not directory:
            return err("Please enter a destination directory.")
        try:
            dest_dir = Path(directory).expanduser().resolve()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / filename
            if has_binary:
                dest_file.write_bytes(state["sanitised_bytes"])
            else:
                dest_file.write_text(state["sanitised_text"], encoding="utf-8")
        except Exception as e:
            return err(f"Could not save file: {e}")
        return f'<p class="success-msg">✓ Saved to <code>{html_lib.escape(str(dest_file))}</code></p>'

    # ── search ─────────────────────────────────────────────────────────────
    @app.post("/search")
    def search():
        term = request.form.get("term", "").strip()
        text = state.get("sanitised_text") or ""
        escaped = html_lib.escape(text)
        count = 0
        if term:
            pat = re.compile(re.escape(html_lib.escape(term)), re.IGNORECASE)
            count = len(pat.findall(escaped))
            escaped = pat.sub(lambda m: f"<mark>{m.group()}</mark>", escaped)
        return render_template("partials/search_result.html",
                               highlighted_text=escaped, term=term, count=count)

    @app.post("/search/add")
    def search_add():
        term = request.form.get("term", "").strip()
        if term:
            sanitizer.add_term(term)
        if state.get("original_text"):
            state["sanitised_text"] = sanitizer.mask_text(state["original_text"])
        ext = state.get("extension", "")
        state["sanitised_bytes"] = None
        if ext in extractor.OFFICE_EXTS and state.get("original_bytes"):
            try:
                state["sanitised_bytes"] = sanitizer.mask_file(state["original_bytes"], ext)
            except Exception:
                pass
        return render_template("partials/obfuscated.html",
                               highlighted_text=html_lib.escape(state.get("sanitised_text") or ""),
                               source_ext=ext,
                               source_filename=state.get("filename", ""))

    # ── rehydrate ──────────────────────────────────────────────────────────
    @app.post("/rehydrate/text")
    def rehydrate_text_route():
        text = request.form.get("text", "")
        if not text.strip():
            return err("No text provided.")
        restored = sanitizer.unmask_text(text)
        state["rehydrated_bytes"] = restored.encode("utf-8")
        state["rehydrated_ext"] = ".txt"
        return render_template("partials/rehydrated.html",
                               preview=restored[:3000], ext=".txt")

    @app.post("/rehydrate/file")
    def rehydrate_file_route():
        file = request.files.get("file")
        if not file or not file.filename:
            return err("No file provided.")
        ext = Path(file.filename).suffix.lower()
        file_bytes = file.read()
        try:
            if ext in extractor.OFFICE_EXTS:
                result = sanitizer.unmask_file(file_bytes, ext)
                state["rehydrated_bytes"] = result
                state["rehydrated_ext"] = ext
                return render_template("partials/rehydrated.html",
                                       preview=None, ext=ext,
                                       filename=file.filename)
            text = file_bytes.decode("utf-8", errors="replace")
            restored = sanitizer.unmask_text(text)
            state["rehydrated_bytes"] = restored.encode("utf-8")
            state["rehydrated_ext"] = ".txt"
            return render_template("partials/rehydrated.html",
                                   preview=restored[:3000], ext=".txt")
        except Exception as e:
            return err(f"Rehydration failed: {e}")

    @app.get("/download/rehydrated")
    def download_rehydrated():
        data = state.get("rehydrated_bytes")
        if not data:
            return "Nothing to download", 404
        ext = state.get("rehydrated_ext", ".txt")
        mime_map = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".txt":  "text/plain",
        }
        return send_file(io.BytesIO(data),
                         mimetype=mime_map.get(ext, "application/octet-stream"),
                         as_attachment=True, download_name=f"rehydrated{ext}")

    # ── dictionary ─────────────────────────────────────────────────────────
    @app.post("/dictionary/add")
    def dictionary_add():
        term = request.form.get("term", "").strip()
        if term:
            sanitizer.add_term(term)
        return render_template("partials/dictionary.html",
                               entries=sanitizer.dictionary())

    @app.post("/dictionary/delete/<int:eid>")
    def dictionary_delete(eid):
        sanitizer.remove_term(eid)
        return render_template("partials/dictionary.html",
                               entries=sanitizer.dictionary())

    @app.get("/dictionary/export")
    def dictionary_export():
        data = json.dumps(sanitizer.export_dictionary(), indent=2).encode("utf-8")
        return send_file(io.BytesIO(data), mimetype="application/json",
                         as_attachment=True, download_name="dictionary.json")

    @app.post("/dictionary/import")
    def dictionary_import():
        file = request.files.get("file")
        if file:
            try:
                data = json.loads(file.read().decode("utf-8"))
                sanitizer.import_dictionary(data)
            except Exception:
                pass
        return render_template("partials/dictionary.html",
                               entries=sanitizer.dictionary())

    # ── patterns ───────────────────────────────────────────────────────────
    @app.post("/patterns/add")
    def patterns_add():
        name = request.form.get("name", "").strip()
        regex = request.form.get("regex", "").strip()
        error = None
        if name and regex:
            try:
                re.compile(regex)
                sanitizer.add_pattern(name, regex)
            except re.error as e:
                error = str(e)
        return render_template("partials/patterns.html",
                               patterns=sanitizer.patterns(), error=error)

    @app.post("/patterns/delete/<int:pid>")
    def patterns_delete(pid):
        sanitizer.remove_pattern(pid)
        return render_template("partials/patterns.html",
                               patterns=sanitizer.patterns(), error=None)

    return app


def serve(host: str = "127.0.0.1", port: int = 5001) -> None:
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError(f"refusing to bind UI to non-loopback host {host!r}")
    create_app().run(host=host, port=port, debug=False)
