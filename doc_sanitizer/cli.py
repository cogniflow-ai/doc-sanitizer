"""
Command-line entry point. The packaged .exe / .app launches via this module.

Usage:
    doc-sanitizer ui [--port 5001]
    doc-sanitizer api [--port 8443]
    doc-sanitizer mask  <file>          # writes <file>.masked.<ext>
    doc-sanitizer unmask <file>         # writes <file>.unmasked.<ext>
    doc-sanitizer token                 # print the API bearer token
    doc-sanitizer paths                 # print where state lives
    doc-sanitizer version
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from doc_sanitizer import __version__, paths
from doc_sanitizer.sanitizer import Sanitizer


def _cmd_ui(args: argparse.Namespace) -> int:
    from doc_sanitizer.web import serve
    serve(host=args.host, port=args.port)
    return 0


def _cmd_api(args: argparse.Namespace) -> int:
    from doc_sanitizer.api import serve
    serve(host=args.host, port=args.port)
    return 0


def _cmd_mask(args: argparse.Namespace) -> int:
    src = Path(args.file)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 2
    s = Sanitizer()
    out = s.mask_file(src.read_bytes(), src.suffix.lower(), auto_add=args.auto_add)
    dst = src.with_suffix(f".masked{src.suffix}")
    dst.write_bytes(out)
    print(dst)
    return 0


def _cmd_unmask(args: argparse.Namespace) -> int:
    src = Path(args.file)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 2
    s = Sanitizer()
    out = s.unmask_file(src.read_bytes(), src.suffix.lower())
    dst = src.with_suffix(f".unmasked{src.suffix}")
    dst.write_bytes(out)
    print(dst)
    return 0


def _cmd_token(_: argparse.Namespace) -> int:
    from doc_sanitizer import crypto
    print(crypto.get_or_create_api_token())
    return 0


def _cmd_paths(_: argparse.Namespace) -> int:
    print(f"data dir   : {paths.user_data_dir()}")
    print(f"db         : {paths.db_path()}")
    print(f"tls dir    : {paths.tls_dir()}")
    print(f"api token  : {paths.api_token_path()}")
    print(f"master key : {paths.master_key_path()} (file fallback only)")
    return 0


def _cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="doc-sanitizer",
                                description="Local document masking/unmasking tool.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pu = sub.add_parser("ui", help="run the local Flask UI (http://127.0.0.1)")
    pu.add_argument("--host", default="127.0.0.1")
    pu.add_argument("--port", type=int, default=5001)
    pu.set_defaults(func=_cmd_ui)

    pa = sub.add_parser("api", help="run the local HTTPS API")
    pa.add_argument("--host", default="127.0.0.1")
    pa.add_argument("--port", type=int, default=8443)
    pa.set_defaults(func=_cmd_api)

    pm = sub.add_parser("mask", help="mask a file in place (writes <name>.masked.<ext>)")
    pm.add_argument("file")
    pm.add_argument("--auto-add", action="store_true",
                    help="auto-add detected candidates to the dictionary")
    pm.set_defaults(func=_cmd_mask)

    pun = sub.add_parser("unmask", help="restore tokens in a file using the dictionary")
    pun.add_argument("file")
    pun.set_defaults(func=_cmd_unmask)

    sub.add_parser("token", help="print the API bearer token").set_defaults(func=_cmd_token)
    sub.add_parser("paths", help="show local state paths").set_defaults(func=_cmd_paths)
    sub.add_parser("version", help="print version").set_defaults(func=_cmd_version)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
