"""
Async single-writer queue for SQLite.
Serializes all DB writes to prevent 'database is locked' errors.
"""

import logging
import queue
import sqlite3
import threading
import time

from settings import DB_BUSY_TIMEOUT, PC_INDEX_DB

logger = logging.getLogger(__name__)


class IndexWriter:
    def __init__(self):
        self.queue = queue.Queue(maxsize=500)
        self._thread = threading.Thread(
            target=self._consumer, daemon=True, name="index-writer"
        )
        self._stop_event = threading.Event()
        self.conn = None

    def start(self):
        self._thread.start()
        logger.info("IndexWriter thread started")

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=5)
        logger.info("IndexWriter thread stopped")

    def push(self, table: str, data: list[dict]):
        if not data:
            return
        try:
            self.queue.put_nowait((table, data))
        except queue.Full:
            logger.warning("IndexWriter queue full — dropping oldest batch")
            try:
                self.queue.get_nowait()  # drop oldest to make room
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait((table, data))
            except queue.Full:
                # Another thread refilled between get and put — log and give up
                logger.error("IndexWriter still full after drop — new batch lost")

    def _consumer(self):
        try:
            PC_INDEX_DB.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(PC_INDEX_DB, timeout=DB_BUSY_TIMEOUT)
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT};")
            self.conn.execute("PRAGMA synchronous=NORMAL;")

            logger.info("IndexWriter connected to DB with WAL mode")
        except Exception as e:
            logger.error(f"IndexWriter DB init failed: {e}")
            return

        batch_size = 50
        retries = 0

        while not self._stop_event.is_set():
            try:
                table, batch = self.queue.get(timeout=1.0)
                if not batch:
                    continue

                for i in range(0, len(batch), batch_size):
                    chunk = batch[i : i + batch_size]
                    try:
                        self._insert_chunk(table, chunk)
                        retries = 0
                    except sqlite3.OperationalError as e:
                        retries += 1
                        if retries > 3:
                            logger.error(f"DB write failed after 3 retries: {e}")
                            break
                        time.sleep(0.5 * retries)
                        continue
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"IndexWriter consumer error: {e}")

        if self.conn:
            self.conn.close()
            logger.info("IndexWriter DB connection closed")

    def _insert_chunk(self, table: str, chunk: list[dict]):
        now = time.time()
        if table == "apps":
            cols = ["name", "exe_path", "version", "publisher", "source", "last_seen"]
            vals = [
                (
                    d["name"],
                    d.get("exe_path"),
                    d.get("version"),
                    d.get("publisher"),
                    d.get("source", "scan"),
                    now,
                )
                for d in chunk
            ]
            query = f"INSERT OR REPLACE INTO apps ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})"
        elif table == "files":
            cols = [
                "filename",
                "extension",
                "full_path",
                "size_bytes",
                "modified_at",
                "directory",
                "last_seen",
            ]
            vals = [
                (
                    d["filename"],
                    d.get("extension", ""),
                    d["full_path"],
                    d.get("size_bytes", 0),
                    d.get("modified_at", 0),
                    d["directory"],
                    now,
                )
                for d in chunk
            ]
            query = f"INSERT OR REPLACE INTO files ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})"
        elif table == "state_snapshots":
            import json

            query = "INSERT INTO state_snapshots (captured_at, windows_json, processes_json, focused_app, clipboard) VALUES (?, ?, ?, ?, ?)"
            vals = [
                (
                    d["captured_at"],
                    json.dumps(d.get("windows", [])),
                    json.dumps(d.get("processes", [])),
                    d.get("focused_app", ""),
                    d.get("clipboard", "")[:500],
                )
                for d in chunk
            ]
        else:
            return

        try:
            self.conn.execute("BEGIN TRANSACTION")
            self.conn.executemany(query, vals)
            self.conn.commit()
        except Exception:
            # Roll back so the next call can open a fresh transaction
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                # Connection is in an unknown state — close and reopen
                try:
                    self.conn.close()
                except Exception:
                    pass
                try:
                    self.conn = sqlite3.connect(PC_INDEX_DB, timeout=DB_BUSY_TIMEOUT)
                    self.conn.execute("PRAGMA journal_mode=WAL;")
                    self.conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT};")
                    self.conn.execute("PRAGMA synchronous=NORMAL;")
                except Exception as conn_err:
                    logger.error(f"IndexWriter reconnection failed: {conn_err}")
            raise
