"""
event_db.py — SQLite event database for surveillance events.

Provides persistent, queryable storage for intrusion events.
Can import from the JSONL evidence log and supports rich queries
for the dashboard and ablation analysis.

Schema:
  events — one row per confirmed-intrusion-frame logged by evidence.py
  ablation_runs — one row per ablation test run
"""

import os
import json
import sqlite3
from datetime import datetime
from contextlib import contextmanager

import config


class EventDB:
    """SQLite database for surveillance events and ablation results."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        incident_id TEXT,
        track_id INTEGER,
        severity TEXT NOT NULL,
        reasons TEXT,
        dwell_seconds REAL DEFAULT 0.0,
        behaviour TEXT,
        roi_name TEXT,
        photo_path TEXT,
        clip_path TEXT,
        photo_sha256 TEXT,
        chain_hash TEXT,
        prev_hash TEXT,
        run_label TEXT DEFAULT 'live'
    );

    CREATE TABLE IF NOT EXISTS ablation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_label TEXT UNIQUE NOT NULL,
        timestamp TEXT NOT NULL,
        config_json TEXT NOT NULL,
        source TEXT,
        total_frames INTEGER DEFAULT 0,
        wall_seconds REAL DEFAULT 0.0,
        avg_fps REAL DEFAULT 0.0,
        total_detections INTEGER DEFAULT 0,
        confirmed_intrusions INTEGER DEFAULT 0,
        low_count INTEGER DEFAULT 0,
        medium_count INTEGER DEFAULT 0,
        high_count INTEGER DEFAULT 0,
        unique_tracks INTEGER DEFAULT 0,
        avg_dwell REAL DEFAULT 0.0,
        max_dwell REAL DEFAULT 0.0,
        notes TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_severity ON events(severity);
    CREATE INDEX IF NOT EXISTS idx_timestamp ON events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_incident ON events(incident_id);
    CREATE INDEX IF NOT EXISTS idx_roi ON events(roi_name);
    CREATE INDEX IF NOT EXISTS idx_run_label ON events(run_label);
    """

    def __init__(self, db_path=None):
        self._db_path = db_path or config.DB_PATH
        self._init_db()

    def _init_db(self):
        """Create tables and indexes if they don't exist."""
        with self._connect() as conn:
            conn.executescript(self.SCHEMA)

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Event CRUD ────────────────────────────────────────────────────────

    def insert_event(self, event_data, run_label="live"):
        """Insert a single event record."""
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO events (
                    timestamp, incident_id, track_id, severity, reasons,
                    dwell_seconds, behaviour, roi_name, photo_path,
                    clip_path, photo_sha256, chain_hash, prev_hash, run_label
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_data.get("timestamp", datetime.now().isoformat()),
                str(event_data.get("incident_id", "")),
                event_data.get("track_id"),
                event_data.get("severity", "LOW"),
                json.dumps(event_data.get("reasons", [])),
                event_data.get("dwell_seconds", 0.0),
                event_data.get("behaviour"),
                event_data.get("roi_name"),
                event_data.get("photo_path"),
                event_data.get("clip_path"),
                event_data.get("photo_sha256"),
                event_data.get("hash"),
                event_data.get("prev_hash"),
                run_label,
            ))

    def import_from_jsonl(self, jsonl_path=None, run_label="live"):
        """
        Import events from the JSONL evidence log.

        Returns:
            Number of records imported.
        """
        jsonl_path = jsonl_path or config.EVIDENCE_LOG_PATH
        if not os.path.exists(jsonl_path):
            print(f"[EventDB] JSONL not found: {jsonl_path}")
            return 0

        count = 0
        with self._connect() as conn:
            # Clear existing events for this run label
            conn.execute("DELETE FROM events WHERE run_label = ?", (run_label,))

            with open(jsonl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        reasons = record.get("reasons", [])
                        if isinstance(reasons, list):
                            reasons = json.dumps(reasons)

                        conn.execute("""
                            INSERT INTO events (
                                timestamp, incident_id, track_id, severity,
                                reasons, dwell_seconds, behaviour, roi_name,
                                photo_path, clip_path, photo_sha256,
                                chain_hash, prev_hash, run_label
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            record.get("timestamp"),
                            str(record.get("incident_id", "")),
                            record.get("track_id"),
                            record.get("severity", "LOW"),
                            reasons,
                            record.get("dwell_seconds", 0.0),
                            record.get("behaviour"),
                            record.get("roi_name"),
                            record.get("photo_path"),
                            record.get("clip_path"),
                            record.get("photo_sha256"),
                            record.get("hash"),
                            record.get("prev_hash"),
                            run_label,
                        ))
                        count += 1
                    except (json.JSONDecodeError, sqlite3.Error) as e:
                        print(f"[EventDB] Skipping bad record: {e}")
                        continue

        print(f"[EventDB] Imported {count} events from {jsonl_path} "
              f"(label={run_label})")
        return count

    # ── Queries ───────────────────────────────────────────────────────────

    def get_events(self, limit=100, offset=0, severity=None, roi_name=None,
                   run_label=None):
        """Get paginated event list with optional filters."""
        query = "SELECT * FROM events WHERE 1=1"
        params = []

        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if roi_name:
            query += " AND roi_name = ?"
            params.append(roi_name)
        if run_label:
            query += " AND run_label = ?"
            params.append(run_label)

        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_event_count(self, run_label=None):
        """Get total event count."""
        with self._connect() as conn:
            if run_label:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM events WHERE run_label = ?",
                    (run_label,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM events"
                ).fetchone()
            return row["cnt"] if row else 0

    def get_severity_counts(self, run_label=None):
        """Get event count grouped by severity."""
        query = "SELECT severity, COUNT(*) as cnt FROM events"
        params = []
        if run_label:
            query += " WHERE run_label = ?"
            params.append(run_label)
        query += " GROUP BY severity ORDER BY severity"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return {row["severity"]: row["cnt"] for row in rows}

    def get_unique_tracks(self, run_label=None):
        """Get count of unique track IDs."""
        query = "SELECT COUNT(DISTINCT incident_id) as cnt FROM events"
        params = []
        if run_label:
            query += " WHERE run_label = ?"
            params.append(run_label)

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            return row["cnt"] if row else 0

    def get_dwell_stats(self, run_label=None):
        """Get dwell time statistics."""
        query = """
            SELECT
                AVG(dwell_seconds) as avg_dwell,
                MAX(dwell_seconds) as max_dwell,
                MIN(CASE WHEN dwell_seconds > 0 THEN dwell_seconds END) as min_dwell
            FROM events
        """
        params = []
        if run_label:
            query += " WHERE run_label = ?"
            params.append(run_label)

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            return {
                "avg": round(row["avg_dwell"] or 0, 2),
                "max": round(row["max_dwell"] or 0, 2),
                "min": round(row["min_dwell"] or 0, 2),
            }

    def get_behaviour_counts(self, run_label=None):
        """Get event count grouped by behaviour."""
        query = """
            SELECT behaviour, COUNT(*) as cnt FROM events
            WHERE behaviour IS NOT NULL
        """
        params = []
        if run_label:
            query += " AND run_label = ?"
            params.append(run_label)
        query += " GROUP BY behaviour ORDER BY cnt DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return {row["behaviour"]: row["cnt"] for row in rows}

    def get_roi_counts(self, run_label=None):
        """Get event count grouped by ROI name."""
        query = """
            SELECT roi_name, COUNT(*) as cnt FROM events
            WHERE roi_name IS NOT NULL
        """
        params = []
        if run_label:
            query += " AND run_label = ?"
            params.append(run_label)
        query += " GROUP BY roi_name ORDER BY cnt DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return {row["roi_name"]: row["cnt"] for row in rows}

    def get_timeline(self, run_label=None, bucket_minutes=1):
        """Get event counts bucketed by time interval."""
        query = """
            SELECT
                SUBSTR(timestamp, 1, 16) as time_bucket,
                COUNT(*) as cnt,
                SUM(CASE WHEN severity='HIGH' THEN 1 ELSE 0 END) as high,
                SUM(CASE WHEN severity='MEDIUM' THEN 1 ELSE 0 END) as medium,
                SUM(CASE WHEN severity='LOW' THEN 1 ELSE 0 END) as low
            FROM events
        """
        params = []
        if run_label:
            query += " WHERE run_label = ?"
            params.append(run_label)
        query += " GROUP BY time_bucket ORDER BY time_bucket"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_full_stats(self, run_label=None):
        """Get comprehensive statistics for the dashboard."""
        return {
            "total_events": self.get_event_count(run_label),
            "severity_counts": self.get_severity_counts(run_label),
            "unique_tracks": self.get_unique_tracks(run_label),
            "dwell_stats": self.get_dwell_stats(run_label),
            "behaviour_counts": self.get_behaviour_counts(run_label),
            "roi_counts": self.get_roi_counts(run_label),
            "timeline": self.get_timeline(run_label),
        }

    # ── Ablation runs ────────────────────────────────────────────────────

    def save_ablation_run(self, run_data):
        """Save an ablation run result."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO ablation_runs (
                    run_label, timestamp, config_json, source,
                    total_frames, wall_seconds, avg_fps,
                    total_detections, confirmed_intrusions,
                    low_count, medium_count, high_count,
                    unique_tracks, avg_dwell, max_dwell, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_data["run_label"],
                run_data.get("timestamp", datetime.now().isoformat()),
                json.dumps(run_data.get("config", {})),
                run_data.get("source", ""),
                run_data.get("total_frames", 0),
                run_data.get("wall_seconds", 0.0),
                run_data.get("avg_fps", 0.0),
                run_data.get("total_detections", 0),
                run_data.get("confirmed_intrusions", 0),
                run_data.get("low_count", 0),
                run_data.get("medium_count", 0),
                run_data.get("high_count", 0),
                run_data.get("unique_tracks", 0),
                run_data.get("avg_dwell", 0.0),
                run_data.get("max_dwell", 0.0),
                run_data.get("notes", ""),
            ))

    def get_ablation_runs(self):
        """Get all ablation run results."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ablation_runs ORDER BY timestamp"
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                try:
                    d["config"] = json.loads(d.get("config_json", "{}"))
                except (json.JSONDecodeError, TypeError):
                    d["config"] = {}
                results.append(d)
            return results

    def clear_ablation_runs(self):
        """Clear all ablation results."""
        with self._connect() as conn:
            conn.execute("DELETE FROM ablation_runs")

    def close(self):
        """No-op — connections are managed per-query via context manager."""
        pass
