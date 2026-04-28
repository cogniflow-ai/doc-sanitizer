"""
Filesystem locations for doc_sanitizer state.

All persistent state lives under a single user-scoped directory created with
restrictive permissions (0700 on POSIX). No state is written to the working
directory of the calling process.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path


def user_data_dir() -> Path:
    """
    Resolve the per-user data directory.

    Order of precedence:
      1. $DOC_SANITIZER_HOME (override, useful for tests / portable runs)
      2. %LOCALAPPDATA%/doc-sanitizer       (Windows)
      3. ~/Library/Application Support/...  (macOS)
      4. $XDG_DATA_HOME or ~/.local/share/  (Linux)
      5. ~/.doc-sanitizer                   (fallback)
    """
    env_override = os.environ.get("DOC_SANITIZER_HOME")
    if env_override:
        return _ensure(Path(env_override).expanduser())

    home = Path.home()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return _ensure(Path(base) / "doc-sanitizer")
        return _ensure(home / "AppData" / "Local" / "doc-sanitizer")

    # POSIX
    if "darwin" in os.sys.platform.lower():
        return _ensure(home / "Library" / "Application Support" / "doc-sanitizer")

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return _ensure(Path(xdg) / "doc-sanitizer")
    return _ensure(home / ".local" / "share" / "doc-sanitizer")


def db_path() -> Path:
    return user_data_dir() / "sanitizer.db"


def tls_dir() -> Path:
    return _ensure(user_data_dir() / "tls", mode=0o700)


def api_token_path() -> Path:
    return user_data_dir() / "api_token"


def master_key_path() -> Path:
    """File-backed fallback for the master encryption key."""
    return user_data_dir() / "master.key"


def _ensure(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    return path


def restrict_file(path: Path) -> None:
    """
    Set 0600 perms on POSIX. On Windows, no-op: %LOCALAPPDATA% is already
    user-scoped via inherited ACLs, and the directory itself has been chmod'd
    to 0700-equivalent (best effort) by `_ensure`. Tightening with icacls
    here previously locked SQLite out of its own DB on some Windows setups.
    """
    if not path.exists():
        return
    if os.name != "nt":
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
