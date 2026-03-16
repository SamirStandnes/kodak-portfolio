import sqlite3
import os
import logging
import shutil
from contextlib import contextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional, Generator

# --- Configuration ---
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'database', 'portfolio.db')

def get_connection() -> sqlite3.Connection:
    """Establishes a connection to the SQLite database with Row factory enabled."""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found at {DB_PATH}. Run setup/initialize_database.py first.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn

@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections. Ensures proper cleanup."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()

def create_backup(label: str = "manual") -> str:
    """Creates a timestamped backup of the database."""
    backup_dir = os.path.join(os.path.dirname(DB_PATH), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"portfolio_{label}_{timestamp}.db")
    
    try:
        shutil.copy2(DB_PATH, backup_path)
        logging.info(f"Backup created: {backup_path}")
        return backup_path
    except Exception as e:
        logging.error(f"Backup failed: {e}")
        raise

def execute_query(query: str, params: tuple = ()) -> List[sqlite3.Row]:
    """Executes a read-only query and returns all results."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
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
    """Execute SQL via cursor and return a pandas DataFrame."""
    import pandas as pd
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    data = cursor.fetchall()
    return pd.DataFrame(data, columns=columns)
