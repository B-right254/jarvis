
"""
Background indexer orchestrator. Starts scanners, manages DB schema, handles lifecycle.
"""
import logging
import settings
import threading
from settings import PC_INDEX_DB, DB_BUSY_TIMEOUT, INDEX_REFRESH_APPS, INDEX_REFRESH_FILES
from indexer.write_queue import IndexWriter
from indexer.app_scanner import scan_apps
from indexer.file_scanner import scan_files
from indexer.state_monitor import monitor_loop

logger = logging.getLogger(__name__)
_writer = IndexWriter()
_stop_event = threading.Event()

def init_db():
    from core.thread_db import get_connection, close_thread_connections
    PC_INDEX_DB.parent.mkdir(parents=True, exist_ok=True)
    close_thread_connections()
    conn = get_connection(PC_INDEX_DB, timeout=DB_BUSY_TIMEOUT)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT};")
    conn.execute("PRAGMA synchronous=NORMAL;")
    
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS apps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, exe_path TEXT, version TEXT,
            publisher TEXT, source TEXT, last_seen REAL,
            UNIQUE(name, exe_path)
        );
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL, extension TEXT, full_path TEXT UNIQUE,
            size_bytes INTEGER, modified_at REAL, directory TEXT, last_seen REAL
        );
        CREATE TABLE IF NOT EXISTS state_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at REAL, windows_json TEXT, processes_json TEXT,
            focused_app TEXT, clipboard TEXT
        );
    """)
    conn.commit()
    logger.info("PC Index DB initialized (WAL mode)")

def start():
    logger.info("Starting PC Indexer...")
    init_db()
    _writer.start()
    
    if getattr(settings, "ENABLE_BACKGROUND_SCANNING", True):
        threading.Thread(target=_app_loop, daemon=True, name="app-scanner").start()
        threading.Thread(target=_file_loop, daemon=True, name="file-scanner").start()
    else:
        logger.info("Background scanning disabled — app/file scanners not started")
    
    threading.Thread(target=monitor_loop, args=(_writer, _stop_event), daemon=True, name="state-monitor").start()
    logger.info("PC Indexer background threads running")

def stop():
    logger.info("Stopping PC Indexer...")
    _stop_event.set()
    _writer.stop()

def _app_loop():
    scan_apps(_writer)
    while not _stop_event.is_set():
        _stop_event.wait(INDEX_REFRESH_APPS)
        if not _stop_event.is_set():
            try: scan_apps(_writer)
            except Exception as e: logger.error(f"App scan failed: {e}")

def _file_loop():
    scan_files(_writer)
    while not _stop_event.is_set():
        _stop_event.wait(INDEX_REFRESH_FILES)
        if not _stop_event.is_set():
            try: scan_files(_writer)
            except Exception as e: logger.error(f"File scan failed: {e}")

