"""
HTTPS client demo — calls the local doc-sanitizer API to mask and unmask
a .docx and a .md file.

Self-contained:
  * spawns `doc-sanitizer api` as a subprocess on a free port
  * trusts the auto-generated self-signed cert (read from the data dir)
  * round-trips both files and asserts the unmasked content matches the original

Run:
    python clients/https_client_demo.py
    # optional: --port 9443  --data-dir /custom/path  --no-spawn (use existing server)
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SAMPLE_MD = HERE / "sample.md"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(url: str, ctx: ssl.SSLContext, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, context=ctx, timeout=2).read()
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"server at {url} did not become healthy in {timeout}s")


def _post_json(url: str, payload: dict, token: str, ctx: ssl.SSLContext) -> dict:
    import json
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_file(url: str, file_path: Path, ext: str,
               token: str, ctx: ssl.SSLContext,
               *, auto_add: bool = False) -> bytes:
    """Send a multipart POST and return the response body bytes."""
    import uuid
    boundary = f"----docsan-{uuid.uuid4().hex}"
    body = bytearray()
    def add(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")
    add("ext", ext)
    if auto_add:
        add("auto_add", "true")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return r.read()


def _resolve_cli() -> tuple[list[str], dict[str, str]]:
    """
    Pick the best invocation of the CLI and return (argv, env_overrides):
      1. ../dist/doc-sanitizer.exe if present (smoke-tests the packaged binary too)
      2. python -m doc_sanitizer.cli (fallback when running from source). When
         using the source-tree fallback we add the project root to PYTHONPATH
         so the demo works without `pip install -e .`.
    """
    exe = ROOT / "dist" / ("doc-sanitizer.exe" if os.name == "nt" else "doc-sanitizer")
    if exe.exists():
        return [str(exe)], {}
    extra_path = str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")
    return [sys.executable, "-m", "doc_sanitizer.cli"], {"PYTHONPATH": extra_path}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=0, help="0 = pick free port")
    p.add_argument("--data-dir", default=None,
                   help="DOC_SANITIZER_HOME for this demo (default: a temp dir)")
    p.add_argument("--no-spawn", action="store_true",
                   help="assume the API is already running on --port; "
                        "you must also pass --data-dir matching its cert/token")
    args = p.parse_args()

    # Ensure the .docx fixture exists. Importable both via `python -m clients.https_client_demo`
    # and direct `python clients/https_client_demo.py`.
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from _sample_docx import make_sample_docx  # type: ignore
    sample_docx = make_sample_docx()
    print(f"[sample] {sample_docx}  ({sample_docx.stat().st_size} bytes)")
    print(f"[sample] {SAMPLE_MD}  ({SAMPLE_MD.stat().st_size} bytes)")

    # Per-demo data dir so we don't clobber the user's real DB / token
    if args.data_dir:
        data_dir = Path(args.data_dir).resolve()
    else:
        import tempfile
        data_dir = Path(tempfile.mkdtemp(prefix="docsan-https-demo-"))
    print(f"[data]   DOC_SANITIZER_HOME = {data_dir}")
    env = {**os.environ, "DOC_SANITIZER_HOME": str(data_dir)}

    port = args.port or _free_port()
    proc: subprocess.Popen | None = None

    if not args.no_spawn:
        cli, env_overrides = _resolve_cli()
        cmd = cli + ["api", "--port", str(port)]
        env = {**env, **env_overrides}
        print(f"[spawn]  {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, env=env,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

    try:
        # cert + token live under the data dir — same conventions as the CLI
        cert_path = data_dir / "tls" / "server.crt"
        token_path = data_dir / "api_token"
        for _ in range(40):  # cert/token are written on first server boot
            if cert_path.exists() and token_path.exists():
                break
            time.sleep(0.25)
        if not cert_path.exists() or not token_path.exists():
            raise RuntimeError(
                f"cert/token not found under {data_dir}; "
                "did the API server fail to start?")

        token = token_path.read_text(encoding="ascii").strip()
        ctx = ssl.create_default_context(cafile=str(cert_path))
        base = f"https://127.0.0.1:{port}"

        _wait_for_health(f"{base}/v1/health", ctx)
        print(f"[ready]  {base}/v1/health -> 200\n")

        # Seed the dictionary explicitly. In real usage you'd either use the UI
        # to review candidates, or trust auto_add for low-risk content. We seed
        # exact terms here so the round-trip is byte-identical.
        seed_terms = [
            "Acme Corporation",
            "Mario Rossi",
            "mario.rossi@acme.example",
            "+39 02 1234 5678",
            "ORD-90215",
        ]
        for t in seed_terms:
            _post_json(f"{base}/v1/dictionary", {"term": t}, token, ctx)
        print(f"[seed]   added {len(seed_terms)} terms to dictionary\n")

        # ── 1. Markdown round-trip via JSON text endpoints ─────────────────
        md_text = SAMPLE_MD.read_text(encoding="utf-8")
        masked = _post_json(f"{base}/v1/mask",
                            {"text": md_text}, token, ctx)["masked"]
        print("--- masked .md (preview) " + "-" * 30)
        print(masked[:500] + ("\n..." if len(masked) > 500 else ""))
        for needle in seed_terms:
            assert needle not in masked, f"masked .md still contains {needle!r}"
        unmasked = _post_json(f"{base}/v1/unmask",
                              {"text": masked}, token, ctx)["unmasked"]
        assert unmasked == md_text, "MD round-trip mismatch!"
        print("[ok]     .md round-trip is byte-exact\n")

        # ── 2. .docx round-trip via /v1/{mask,unmask}/file ─────────────────
        masked_docx = _post_file(f"{base}/v1/mask/file", sample_docx,
                                 ext=".docx", token=token, ctx=ctx)
        out_masked = HERE / "sample.masked.docx"
        out_masked.write_bytes(masked_docx)
        print(f"[write]  {out_masked}  ({len(masked_docx)} bytes)")

        rehydrated_docx = _post_file(f"{base}/v1/unmask/file", out_masked,
                                     ext=".docx", token=token, ctx=ctx)
        out_rehyd = HERE / "sample.rehydrated.docx"
        out_rehyd.write_bytes(rehydrated_docx)
        print(f"[write]  {out_rehyd}  ({len(rehydrated_docx)} bytes)")

        # Verify by re-extracting text from each .docx with python-docx directly.
        import io
        from docx import Document  # comes with the doc-sanitizer dependencies

        def _docx_text(buf: bytes) -> str:
            d = Document(io.BytesIO(buf))
            return "\n".join(p.text for p in d.paragraphs)

        original_text = _docx_text(sample_docx.read_bytes())
        rehyd_text    = _docx_text(rehydrated_docx)
        masked_text   = _docx_text(masked_docx)

        for needle in seed_terms:
            assert needle in original_text, f"setup: {needle!r} missing from original"
            assert needle in rehyd_text,    f"rehyd:  {needle!r} missing from rehydrated"
            assert needle not in masked_text, f"leak:  {needle!r} still in masked"
        print("[ok]     .docx mask leaves no plaintext + .docx unmask restores all terms\n")

        # ── 3. Inspect the dictionary the server built ─────────────────────
        import json as _json
        req = urllib.request.Request(f"{base}/v1/dictionary",
                                     headers={"Authorization": f"Bearer {token}"})
        entries = _json.loads(urllib.request.urlopen(req, context=ctx).read())
        print(f"[dict]   server built {len(entries['entries'])} dictionary entries:")
        for e in entries["entries"][:10]:
            print(f"           {e['token']:>14}  ->  {e['original_term']}")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if not args.data_dir:
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
