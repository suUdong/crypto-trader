"""Domain exceptions for the storage layer.

Codex review (2026-04-07) flagged that raw ``sqlite3.IntegrityError`` and
``ValueError`` were leaking out of the store, coupling callers to the
backend. This module defines a small hierarchy that other modules can
catch without importing ``sqlite3``.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base for all storage-layer errors."""


class ValidationError(StorageError, ValueError):
    """Raised when a row fails invariants before any DB call.

    Inherits from ``ValueError`` so existing ``except ValueError`` blocks
    keep working during the migration period.
    """


class IntegrityError(StorageError):
    """Raised when a backend uniqueness/integrity constraint is violated.

    Wraps the backend-specific exception so callers stay backend-agnostic.
    """
