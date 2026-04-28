"""
Backwards-compatible launcher. Delegates to doc_sanitizer.web.

Run:
    python app.py            # local UI on http://127.0.0.1:5001
    python -m doc_sanitizer.cli ui --port 5001
    python -m doc_sanitizer.cli api --port 8443
"""
from doc_sanitizer.web import create_app, serve

app = create_app()  # exported for `flask run` / WSGI hosts (local-only!)


if __name__ == "__main__":
    serve(host="127.0.0.1", port=5001)
