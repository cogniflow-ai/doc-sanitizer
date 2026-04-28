"""
Compatibility shim — delegates to the encrypted SecretStore in doc_sanitizer.
The new code path is `doc_sanitizer.secrets_store.SecretStore` (or the
high-level `doc_sanitizer.Sanitizer` facade).
"""
from doc_sanitizer.secrets_store import default_store


def init_db() -> None:
    default_store()  # creates schema on first call


def get_dictionary():
    return default_store().get_dictionary()


def add_to_dictionary(term: str, token: str | None = None) -> None:
    default_store().add_term(term, token=token)


def delete_from_dictionary(entry_id: int) -> None:
    default_store().delete_term(entry_id)


def export_dictionary():
    return default_store().export_dictionary()


def import_dictionary(data) -> None:
    default_store().import_dictionary(data)


def get_patterns():
    return default_store().get_patterns()


def add_pattern(name: str, regex: str) -> None:
    default_store().add_pattern(name, regex)


def delete_pattern(pat_id: int) -> None:
    default_store().delete_pattern(pat_id)
