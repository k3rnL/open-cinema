from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.backends.signals import connection_created


def _is_memory_database(name: object) -> bool:
    value = str(name)
    return value == ":memory:" or "mode=memory" in value


def configure_sqlite_connection(sender, connection, **kwargs) -> None:
    """Apply the appliance SQLite concurrency policy to every new connection."""

    if connection.vendor != "sqlite":
        return
    busy_timeout = settings.SQLITE_BUSY_TIMEOUT_MS
    if isinstance(busy_timeout, bool) or not isinstance(busy_timeout, int):
        raise ImproperlyConfigured("SQLITE_BUSY_TIMEOUT_MS must be an integer")
    if busy_timeout < 1 or busy_timeout > 60000:
        raise ImproperlyConfigured("SQLITE_BUSY_TIMEOUT_MS must be between 1 and 60000")
    wal_autocheckpoint = settings.SQLITE_WAL_AUTOCHECKPOINT_PAGES
    if (
        isinstance(wal_autocheckpoint, bool)
        or not isinstance(wal_autocheckpoint, int)
        or wal_autocheckpoint < 1
        or wal_autocheckpoint > 100000
    ):
        raise ImproperlyConfigured(
            "SQLITE_WAL_AUTOCHECKPOINT_PAGES must be between 1 and 100000"
        )

    with connection.cursor() as cursor:
        cursor.execute(f"PRAGMA busy_timeout = {busy_timeout}")
        cursor.execute("PRAGMA foreign_keys = ON")
        if not _is_memory_database(connection.settings_dict["NAME"]):
            cursor.execute("PRAGMA journal_mode = WAL")
            mode = cursor.fetchone()[0]
            if str(mode).lower() != "wal":
                raise ImproperlyConfigured(f"SQLite refused WAL mode and reported {mode!r}")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute(f"PRAGMA wal_autocheckpoint = {wal_autocheckpoint}")


def install_sqlite_connection_policy() -> None:
    connection_created.connect(
        configure_sqlite_connection,
        dispatch_uid="open-cinema-orchestration-sqlite-policy-v1",
    )
