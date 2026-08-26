import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic, sleep

import pytest
from django.conf import settings
from django.db.backends.sqlite3.base import DatabaseWrapper

from core.orchestration.sqlite_policy import configure_sqlite_connection


def _database_settings(path):
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(path),
        "OPTIONS": {"timeout": 5},
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "TIME_ZONE": None,
        "USER": "",
        "PASSWORD": "",
        "HOST": "",
        "PORT": "",
        "TEST": {},
    }


@pytest.mark.django_db
def test_file_sqlite_connection_enables_wal_and_bounded_wait(tmp_path) -> None:
    database = DatabaseWrapper(_database_settings(tmp_path / "wal.sqlite3"), "wal-test")
    try:
        database.connect()
        configure_sqlite_connection(None, database)
        with database.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode")
            assert cursor.fetchone()[0].lower() == "wal"
            cursor.execute("PRAGMA busy_timeout")
            assert cursor.fetchone()[0] == settings.SQLITE_BUSY_TIMEOUT_MS
            cursor.execute("PRAGMA synchronous")
            assert cursor.fetchone()[0] == 1
            cursor.execute("PRAGMA wal_autocheckpoint")
            assert cursor.fetchone()[0] == settings.SQLITE_WAL_AUTOCHECKPOINT_PAGES
    finally:
        database.close()


def test_wal_allows_web_read_during_short_orchestrator_write(tmp_path) -> None:
    path = tmp_path / "concurrent.sqlite3"
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        connection.execute("CREATE TABLE desired_version (version INTEGER NOT NULL)")

    writer_started = Barrier(2)

    def orchestrator_write():
        with sqlite3.connect(path, timeout=1) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO desired_version VALUES (1)")
            writer_started.wait()
            sleep(0.05)
            connection.commit()

    def web_read():
        writer_started.wait()
        started = monotonic()
        with sqlite3.connect(path, timeout=1) as connection:
            observed_during_write = connection.execute(
                "SELECT COUNT(*) FROM desired_version"
            ).fetchone()[0]
        return observed_during_write, monotonic() - started

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(orchestrator_write)
        reader = pool.submit(web_read)
        observed, elapsed = reader.result(timeout=2)
        writer.result(timeout=2)

    with sqlite3.connect(path) as connection:
        observed_after_commit = connection.execute(
            "SELECT COUNT(*) FROM desired_version"
        ).fetchone()[0]

    assert observed == 0
    assert observed_after_commit == 1
    assert elapsed < 0.25


@pytest.mark.django_db
def test_project_database_uses_bounded_sqlite_timeout() -> None:
    assert settings.DATABASES["default"]["OPTIONS"]["timeout"] == 5
