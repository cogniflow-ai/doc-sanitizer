"""
doc_sanitizer — local-first document masking and rehydration.

Public API:
    Sanitizer            — high-level facade for mask/unmask operations
    mask_text            — convenience function
    unmask_text          — convenience function
    mask_file            — convenience function (bytes in, bytes out)
    unmask_file          — convenience function (bytes in, bytes out)
"""
from doc_sanitizer.sanitizer import (
    Sanitizer,
    mask_text,
    unmask_text,
    mask_file,
    unmask_file,
)

__version__ = "0.2.0"

__all__ = [
    "Sanitizer",
    "mask_text",
    "unmask_text",
    "mask_file",
    "unmask_file",
    "__version__",
]
