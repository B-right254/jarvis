"""
Thread-local SQLite connection management.

Provides thread-safe connection handling to prevent "SQLite objects created in
a thread can only be used in that same thread" errors.

Usage:
    from core.thread_db import get_connection, close_thread_connections
    
    # In any thread:
    with get_connection(MEMORY_DB) as conn:
        conn.execute("SELECT 1")
    
    # On thread exit (optional cleanup):
    close_thread_connections()
"""

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Thread-local storage for connections
_thread_local = threading.local()
# Global registry: thread_ident -> [(db_path, conn), ...] for cross-thread cleanup
_global_connections: dict[int, list[tuple[str, sqlite3.Connection]]] = {}
_global_lock = threading.Lock()


def _get_thread_connections() -> dict:
    """Get or create the connection dict for the current thread."""
    if not hasattr(_thread_local, 'connections'):
        _thread_local.connections = {}
    return _thread_local.connections


def get_connection(db_path: Path, timeout: float = 5.0) -> sqlite3.Connection:
    """
    Get or create a SQLite connection for the current thread.
    
    Each thread gets its own connection to avoid thread-safety issues.
    Connections are cached per-thread for reuse.
    
    Args:
        db_path: Path to the SQLite database
        timeout: Busy timeout in seconds
        
    Returns:
        sqlite3.Connection configured for the current thread
    """
    connections = _get_thread_connections()
    db_key = str(db_path.resolve())
    
    if db_key not in connections:
        logger.debug(f"Creating new SQLite connection for thread {threading.current_thread().ident}")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_key, timeout=timeout)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        connections[db_key] = conn
        # Register in global registry for cross-thread cleanup
        tid = threading.current_thread().ident
        with _global_lock:
            if tid not in _global_connections:
                _global_connections[tid] = []
            _global_connections[tid].append((db_key, conn))
    
    return connections[db_key]


@contextmanager
def connection_context(db_path: Path, timeout: float = 5.0):
    """
    Context manager for thread-safe SQLite connections.
    
    Usage:
        with connection_context(MEMORY_DB) as conn:
            conn.execute("SELECT 1")
    
    The connection is returned to the thread's cache (not closed) for reuse.
    """
    conn = get_connection(db_path, timeout)
    try:
        yield conn
    finally:
        # Connection stays cached in thread for reuse
        pass


def close_thread_connections():
    """Close all SQLite connections for the current thread."""
    if not hasattr(_thread_local, "connections"):
        return

    connections = _thread_local.connections
    tid = threading.current_thread().ident
    for db_key, conn in list(connections.items()):
        try:
            logger.debug(f"Closing SQLite connection for {db_key} in thread {tid}")
            conn.close()
        except Exception as e:
            logger.warning(f"Error closing connection {db_key}: {e}")
    connections.clear()
    # Remove from global registry
    with _global_lock:
        _global_connections.pop(tid, None)


def close_all_connections():
    """
    Close all SQLite connections across all threads.
    Use during shutdown to ensure no connections leak.
    """
    with _global_lock:
        for tid, conns in list(_global_connections.items()):
            for db_key, conn in conns:
                try:
                    conn.close()
                except Exception as e:
                    logger.warning(f"Error closing connection for {db_key} in thread {tid}: {e}")
        _global_connections.clear()
    # Also close current thread's connections
    close_thread_connections()


# Convenience functions for common databases
def get_memory_connection(timeout: float = 5.0):
    """Get a connection to MEMORY_DB for the current thread."""
    from settings import MEMORY_DB
    return get_connection(MEMORY_DB, timeout)


def get_pc_index_connection(timeout: float = 5.0):
    """Get a connection to PC_INDEX_DB for the current thread."""
    from settings import PC_INDEX_DB
    return get_connection(PC_INDEX_DB, timeout)


def get_skills_connection(timeout: float = 5.0):
    """Get a connection to SKILLS_DB for the current thread."""
    from settings import SKILLS_DB
    return get_connection(SKILLS_DB, timeout)
