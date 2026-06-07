"""
api/store.py — SQLite-backed incident store.

Acts as the "database" layer between the API and the LangGraph state.
Tracks incident status, result snapshots, and HITL state.
Modified to persist state across restarts using SQLite, while keeping
the event bus in-memory for active streaming connections.
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi.encoders import jsonable_encoder

from api.schemas import IncidentStatusEnum
import config


class IncidentRecord:
    """
    Runtime record for a single incident.
    Created when a trigger fires, updated as the graph progresses.
    """

    def __init__(self, incident_id: str, service: str, severity: str, triggered_at: datetime, _save_callback=None):
        self.incident_id:  str                   = incident_id
        self.service:      str                   = service
        self.severity:     str                   = severity
        self.triggered_at: datetime              = triggered_at
        self.status:       IncidentStatusEnum    = IncidentStatusEnum.PENDING
        self.completed_at: Optional[datetime]    = None

        # Snapshot of the final LangGraph state once complete
        self.final_state:  Optional[dict]        = None

        # Error message if the graph crashed
        self.error:        Optional[str]         = None

        # Callback to trigger SQLite save
        self._save_callback = _save_callback

        # ── Event bus for SSE streaming ───────────────────────────────────────
        # Each subscriber gets their own queue. runner.py calls publish().
        self._event_subs: list[queue.Queue] = []
        self._event_lock  = threading.Lock()

    def _save(self):
        """Triggers a save to SQLite if the callback is configured."""
        if self._save_callback:
            self._save_callback(self)

    def mark_running(self):
        self.status = IncidentStatusEnum.RUNNING
        self._save()
        self.publish({"event": "status", "data": "running"})

    def mark_waiting(self):
        """Called when the graph hits the HITL interrupt."""
        self.status = IncidentStatusEnum.WAITING
        self._save()
        self.publish({"event": "status", "data": "waiting", "message": "Paused — awaiting engineer input"})

    def mark_completed(self, final_state: dict):
        self.status       = IncidentStatusEnum.COMPLETED
        self.completed_at = datetime.now(timezone.utc)
        self.final_state  = final_state
        self._save()
        self.publish({"event": "status", "data": "completed"})
        self._close_all_subs()

    def mark_failed(self, error: str):
        self.status       = IncidentStatusEnum.FAILED
        self.completed_at = datetime.now(timezone.utc)
        self.error        = error
        self._save()
        self.publish({"event": "status", "data": "failed", "error": error})
        self._close_all_subs()

    # ── Event bus ─────────────────────────────────────────────────────────────

    def subscribe(self) -> queue.Queue:
        """Register a new SSE listener. Returns a queue to read events from."""
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._event_lock:
            self._event_subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        """Remove an SSE listener (called when client disconnects)."""
        with self._event_lock:
            try:
                self._event_subs.remove(q)
            except ValueError:
                pass

    def publish(self, event: dict):
        """Push an event to all active SSE subscribers (non-blocking)."""
        with self._event_lock:
            for q in self._event_subs:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass   # slow consumer — drop the event

    def _close_all_subs(self):
        """Send a sentinel None to tell all SSE listeners the stream is done."""
        with self._event_lock:
            for q in self._event_subs:
                try:
                    q.put_nowait(None)   # None = stream closed
                except queue.Full:
                    pass


class IncidentStore:
    """
    Thread-safe SQLite-backed store for all active/completed incidents.
    Keeps active objects in memory so SSE subscriptions work seamlessly.
    """

    def __init__(self):
        self._lock: threading.Lock = threading.Lock()
        self._records: dict[str, IncidentRecord] = {}
        
        self.db_path = config.SQLITE_DB_PATH
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    service TEXT,
                    severity TEXT,
                    triggered_at TEXT,
                    status TEXT,
                    completed_at TEXT,
                    final_state TEXT,
                    error TEXT
                )
            ''')
            conn.commit()

    def _save_record(self, record: IncidentRecord):
        """Internal callback to upsert the record into SQLite."""
        with self._lock:
            with self._get_conn() as conn:
                conn.execute('''
                    INSERT INTO incidents (
                        incident_id, service, severity, triggered_at, status, completed_at, final_state, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(incident_id) DO UPDATE SET
                        status = excluded.status,
                        completed_at = excluded.completed_at,
                        final_state = excluded.final_state,
                        error = excluded.error
                ''', (
                    record.incident_id,
                    record.service,
                    record.severity,
                    record.triggered_at.isoformat(),
                    record.status.value,
                    record.completed_at.isoformat() if record.completed_at else None,
                    json.dumps(jsonable_encoder(record.final_state)) if record.final_state else None,
                    record.error
                ))
                conn.commit()

    def _row_to_record(self, row) -> IncidentRecord:
        """Convert a SQLite row tuple into an IncidentRecord object."""
        rec = IncidentRecord(
            incident_id=row[0],
            service=row[1],
            severity=row[2],
            triggered_at=datetime.fromisoformat(row[3]),
            _save_callback=self._save_record
        )
        rec.status = IncidentStatusEnum(row[4])
        rec.completed_at = datetime.fromisoformat(row[5]) if row[5] else None
        rec.final_state = json.loads(row[6]) if row[6] else None
        rec.error = row[7]
        return rec

    def create(
        self,
        incident_id:  str,
        service:      str,
        severity:     str,
        triggered_at: datetime,
    ) -> IncidentRecord:
        """Create and register a new incident record. Raises if already exists."""
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT incident_id FROM incidents WHERE incident_id = ?", (incident_id,))
                if cur.fetchone():
                    raise ValueError(f"Incident {incident_id} already exists")

            record = IncidentRecord(
                incident_id=incident_id,
                service=service,
                severity=severity,
                triggered_at=triggered_at,
                _save_callback=self._save_record
            )
            self._records[incident_id] = record
            
        # Trigger save (acquires lock safely inside _save_record)
        self._save_record(record)
        return record

    def get(self, incident_id: str) -> Optional[IncidentRecord]:
        """Return the record or None if not found. Fetches from SQLite if not in RAM."""
        with self._lock:
            if incident_id in self._records:
                return self._records[incident_id]
            
            with self._get_conn() as conn:
                cur = conn.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
                row = cur.fetchone()
                if row:
                    record = self._row_to_record(row)
                    self._records[incident_id] = record
                    return record
        return None

    def get_or_raise(self, incident_id: str) -> IncidentRecord:
        """Return the record or raise KeyError."""
        record = self.get(incident_id)
        if record is None:
            raise KeyError(f"Incident {incident_id} not found")
        return record

    def all(self) -> list[IncidentRecord]:
        """Return all records, newest-first by triggered_at."""
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT * FROM incidents ORDER BY triggered_at DESC")
                results = []
                for row in cur.fetchall():
                    inc_id = row[0]
                    if inc_id in self._records:
                        results.append(self._records[inc_id])
                    else:
                        record = self._row_to_record(row)
                        self._records[inc_id] = record
                        results.append(record)
                
                # Double check sorting just in case string comparison of ISO dates was weird in SQLite
                return sorted(results, key=lambda r: r.triggered_at, reverse=True)

    def count(self) -> int:
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT COUNT(*) FROM incidents")
                return cur.fetchone()[0]
