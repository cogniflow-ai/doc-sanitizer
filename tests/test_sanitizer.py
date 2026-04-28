"""Smoke tests for the library and API. Each test gets its own data dir."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_home(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="docsan-"))
    monkeypatch.setenv("DOC_SANITIZER_HOME", str(tmp))
    # Reset any module caches
    from doc_sanitizer import secrets_store
    secrets_store.reset_default_store()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_mask_unmask_roundtrip(isolated_home):
    from doc_sanitizer import Sanitizer
    s = Sanitizer()
    s.add_term("Acme Corp")
    s.add_term("Mario Rossi")
    masked = s.mask_text("Mario Rossi works at Acme Corp.")
    assert "Mario Rossi" not in masked
    assert "Acme Corp" not in masked
    assert s.unmask_text(masked) == "Mario Rossi works at Acme Corp."


def test_case_insensitive_dedup(isolated_home):
    from doc_sanitizer import Sanitizer
    s = Sanitizer()
    a = s.add_term("Acme Corp")
    b = s.add_term("ACME corp")
    assert a["id"] == b["id"]
    assert a["token"] == b["token"]


def test_secrets_are_encrypted_at_rest(isolated_home):
    from doc_sanitizer import Sanitizer, paths
    s = Sanitizer()
    s.add_term("super-secret-customer-name")
    raw = paths.db_path().read_bytes()
    assert b"super-secret-customer-name" not in raw, \
        "plaintext leaked into DB file"


def test_api_requires_bearer_token(isolated_home):
    from doc_sanitizer.api import create_app
    from doc_sanitizer import crypto
    app = create_app(token=crypto.get_or_create_api_token())
    c = app.test_client()
    assert c.post("/v1/mask", json={"text": "x"}).status_code == 401


def test_api_mask_unmask(isolated_home):
    from doc_sanitizer.api import create_app
    from doc_sanitizer import crypto
    tok = crypto.get_or_create_api_token()
    app = create_app(token=tok)
    c = app.test_client()
    H = {"Authorization": f"Bearer {tok}"}
    r = c.post("/v1/mask", json={"text": "Mario Rossi", "auto_add": True}, headers=H)
    assert r.status_code == 200
    masked = r.get_json()["masked"]
    assert "Mario Rossi" not in masked
    r2 = c.post("/v1/unmask", json={"text": masked}, headers=H)
    assert r2.get_json()["unmasked"] == "Mario Rossi"


def test_api_rejects_bad_regex(isolated_home):
    from doc_sanitizer.api import create_app
    from doc_sanitizer import crypto
    tok = crypto.get_or_create_api_token()
    app = create_app(token=tok)
    c = app.test_client()
    H = {"Authorization": f"Bearer {tok}"}
    r = c.post("/v1/patterns", json={"name": "bad", "regex": "["}, headers=H)
    assert r.status_code == 400


def test_health_does_not_require_auth(isolated_home):
    from doc_sanitizer.api import create_app
    from doc_sanitizer import crypto
    app = create_app(token=crypto.get_or_create_api_token())
    assert app.test_client().get("/v1/health").status_code == 200


def test_api_refuses_non_loopback_bind(isolated_home):
    from doc_sanitizer.api import serve
    with pytest.raises(ValueError):
        serve(host="0.0.0.0")


def test_module_level_helpers(isolated_home):
    from doc_sanitizer import mask_text, unmask_text
    # auto_add=True so the helper picks up candidates without an explicit add_term
    masked = mask_text("Mario Rossi", auto_add=True)
    assert "Mario Rossi" not in masked
    assert unmask_text(masked) == "Mario Rossi"
