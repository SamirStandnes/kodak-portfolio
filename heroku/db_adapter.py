"""
PostgreSQL database adapter for Heroku deployment.
Provides the same interface as kodak/shared/db.py but uses PostgreSQL.
"""
import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Generator

# Import SQL translation
from heroku.sql_compat import translate_query

# --- Configuration ---
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Heroku provides postgres:// but psycopg2 needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


class DictRow(dict):
    """A dict subclass that also supports index-based access like sqlite3.Row."""
    def __init__(self, data: dict):
        super().__init__(data)
        self._keys = list(data.keys())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self[self._keys[key]]
        return super().__getitem__(key)

    def keys(self):
        return self._keys


class TranslatingCursor:
    """A cursor wrapper that translates SQLite SQL to PostgreSQL."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        pg_query = translate_query(query)
        if params:
            return self._cursor.execute(pg_query, params)
        return self._cursor.execute(pg_query)

    def executemany(self, query, params_list):
        pg_query = translate_query(query)
        return self._cursor.executemany(pg_query, params_list)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        if size:
            return self._cursor.fetchmany(size)
        return self._cursor.fetchmany()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    def close(self):
        return self._cursor.close()

    def __iter__(self):
        return iter(self._cursor)


class TranslatingConnection:
    """A connection wrapper that returns translating cursors."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self, cursor_factory=None):
        if cursor_factory:
            return TranslatingCursor(self._conn.cursor(cursor_factory=cursor_factory))
        return TranslatingCursor(self._conn.cursor())

    def execute(self, query, params=None):
        """Direct execute on connection (used by some code paths)."""
        pg_query = translate_query(query)
        cursor = self._conn.cursor()
        if params:
            cursor.execute(pg_query, params)
        else:
            cursor.execute(pg_query)
        return cursor

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def get_connection():
    """Establishes a connection to the PostgreSQL database."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set")

    conn = psycopg2.connect(DATABASE_URL)
    return TranslatingConnection(conn)


@contextmanager
def get_db_connection() -> Generator[Any, None, None]:
    """Context manager for database connections. Ensures proper cleanup."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def create_backup(label: str = "manual") -> str:
    """
    Backup stub for PostgreSQL.
    On Heroku, backups are managed by Heroku Postgres addon.
    """
    logging.info(f"Backup requested with label '{label}' - use Heroku Postgres backups instead")
    return "heroku-managed"


def execute_query(query: str, params: tuple = ()) -> List[DictRow]:
    """Executes a read-only query and returns all results as dict-like rows."""
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [DictRow(dict(row)) for row in rows]
    finally:
        conn.close()


def execute_scalar(query: str, params: tuple = ()) -> Any:
    """Executes a query and returns the first column of the first row."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        conn.close()


def execute_non_query(query: str, params: tuple = ()) -> int:
    """Executes a write query (INSERT, UPDATE, DELETE) and returns row count."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        conn.rollback()
        logging.error(f"Database error: {e}")
        raise
    finally:
        conn.close()


def execute_batch(query: str, params_list: List[tuple]) -> int:
    """Executes a batch INSERT/UPDATE."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.executemany(query, params_list)
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        conn.rollback()
        logging.error(f"Database batch error: {e}")
        raise
    finally:
        conn.close()


def query_df(query: str, conn, params=None):
    """
    Execute SQL and return a pandas DataFrame.

    Uses the TranslatingCursor directly (SQL gets translated, ? -> %s, etc.)
    instead of pd.read_sql_query which doesn't support custom connection wrappers.
    """
    import pandas as pd
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    data = cursor.fetchall()
    return pd.DataFrame(data, columns=columns)
