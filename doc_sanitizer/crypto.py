"""
Master-key management and TLS certificate generation.

The master key encrypts sensitive columns (`original_term`) in the secrets DB.
It is stored in the OS keyring when available, with a file-backed fallback
under `user_data_dir()/master.key` (chmod 0600). Tokens — which are opaque
identifiers like `__TERM_42__` — are NOT secret and remain in plaintext so
they can be used as substitution targets without decryption on every read.
"""
from __future__ import annotations

import datetime as _dt
import os
import secrets
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from doc_sanitizer import paths as _paths

_KEYRING_SERVICE = "doc-sanitizer"
_KEYRING_USER = "master-key"


def _try_keyring_get() -> Optional[bytes]:
    try:
        import keyring  # type: ignore
        val = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
        if val:
            return val.encode("ascii")
    except Exception:
        return None
    return None


def _try_keyring_set(key: bytes) -> bool:
    try:
        import keyring  # type: ignore
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, key.decode("ascii"))
        return True
    except Exception:
        return False


def _read_key_file() -> Optional[bytes]:
    path = _paths.master_key_path()
    if not path.exists():
        return None
    try:
        data = path.read_bytes().strip()
        return data or None
    except OSError:
        return None


def _write_key_file(key: bytes) -> None:
    path = _paths.master_key_path()
    path.write_bytes(key)
    _paths.restrict_file(path)


def get_or_create_master_key() -> bytes:
    """
    Returns the URL-safe base64 Fernet key. Generates one on first use.
    Storage order: OS keyring (preferred) → key file (fallback).
    """
    if (k := _try_keyring_get()):
        return k
    if (k := _read_key_file()):
        # Migrate to keyring if newly available
        _try_keyring_set(k)
        return k
    new_key = Fernet.generate_key()
    if not _try_keyring_set(new_key):
        _write_key_file(new_key)
    return new_key


def get_fernet() -> Fernet:
    return Fernet(get_or_create_master_key())


def encrypt(plaintext: str) -> bytes:
    return get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    try:
        return get_fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as e:
        raise RuntimeError(
            "Failed to decrypt secrets DB — master key mismatch. "
            "If you migrated machines, restore the master key from the original "
            "OS keyring or master.key file."
        ) from e


# ── API bearer token ─────────────────────────────────────────────────────────

def get_or_create_api_token() -> str:
    """Generate / load the bearer token used by the local HTTPS API."""
    path = _paths.api_token_path()
    if path.exists():
        token = path.read_text(encoding="ascii").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="ascii")
    _paths.restrict_file(path)
    return token


# ── TLS certificate generation ───────────────────────────────────────────────

def get_or_create_tls_cert(common_name: str = "localhost",
                            valid_years: int = 5) -> tuple[Path, Path]:
    """
    Returns (cert_path, key_path). Generates a self-signed RSA-2048 cert on
    first use. Cert file is 0644; key file is 0600.
    """
    cert_dir = _paths.tls_dir()
    cert_path = cert_dir / "server.crt"
    key_path = cert_dir / "server.key"
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "doc-sanitizer (local)"),
    ])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(days=1))
        .not_valid_after(now + _dt.timedelta(days=365 * valid_years))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(__import__("ipaddress").IPv4Address("127.0.0.1")),
                x509.IPAddress(__import__("ipaddress").IPv6Address("::1")),
            ]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    _paths.restrict_file(key_path)
    return cert_path, key_path
