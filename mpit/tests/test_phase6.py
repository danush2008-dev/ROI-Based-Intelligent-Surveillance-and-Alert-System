"""
test_phase6.py — Unit tests for Phase 6: Event DB, ablation, dashboard.

Tests the SQLite event database, ablation profile definitions,
and dashboard API endpoints.
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import config


# ── EventDB Tests ─────────────────────────────────────────────────────────

class TestEventDB:
    """Test the SQLite event database."""

    @pytest.fixture
    def tmp_db(self, tmp_path):
        """Create a temporary database."""
        from event_db import EventDB
        db_path = str(tmp_path / "test_events.db")
        return EventDB(db_path=db_path)

    def test_create_db(self, tmp_db):
        """Database should initialize with empty tables."""
        assert tmp_db.get_event_count() == 0

    def test_insert_event(self, tmp_db):
        """Inserting an event should increase the count."""
        tmp_db.insert_event({
            "timestamp": "2026-10-09T20:00:00",
            "incident_id": "1",
            "severity": "HIGH",
            "reasons": ["dwell>=30s"],
            "dwell_seconds": 35.0,
            "roi_name": "entrance",
        })
        assert tmp_db.get_event_count() == 1

    def test_severity_counts(self, tmp_db):
        """Severity counts should group events correctly."""
        for sev in ["LOW", "LOW", "MEDIUM", "HIGH", "HIGH", "HIGH"]:
            tmp_db.insert_event({
                "timestamp": "2026-10-09T20:00:00",
                "incident_id": "1",
                "severity": sev,
            })
        counts = tmp_db.get_severity_counts()
        assert counts.get("LOW") == 2
        assert counts.get("MEDIUM") == 1
        assert counts.get("HIGH") == 3

    def test_unique_tracks(self, tmp_db):
        """Should count distinct incident IDs."""
        for iid in ["1", "1", "2", "3", "3"]:
            tmp_db.insert_event({
                "timestamp": "2026-10-09T20:00:00",
                "incident_id": iid,
                "severity": "LOW",
            })
        assert tmp_db.get_unique_tracks() == 3

    def test_dwell_stats(self, tmp_db):
        """Should compute avg/max/min dwell correctly."""
        for dwell in [5.0, 10.0, 15.0, 20.0]:
            tmp_db.insert_event({
                "timestamp": "2026-10-09T20:00:00",
                "incident_id": "1",
                "severity": "LOW",
                "dwell_seconds": dwell,
            })
        stats = tmp_db.get_dwell_stats()
        assert stats["avg"] == 12.5
        assert stats["max"] == 20.0
        assert stats["min"] == 5.0

    def test_get_events_pagination(self, tmp_db):
        """Should support limit/offset pagination."""
        for i in range(20):
            tmp_db.insert_event({
                "timestamp": f"2026-10-09T20:{i:02d}:00",
                "incident_id": str(i),
                "severity": "LOW",
            })
        page1 = tmp_db.get_events(limit=5, offset=0)
        page2 = tmp_db.get_events(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        assert page1[0]["incident_id"] != page2[0]["incident_id"]

    def test_get_events_filter_severity(self, tmp_db):
        """Should filter events by severity."""
        tmp_db.insert_event({"timestamp": "2026-10-09T20:00:00",
                            "incident_id": "1", "severity": "HIGH"})
        tmp_db.insert_event({"timestamp": "2026-10-09T20:00:00",
                            "incident_id": "2", "severity": "LOW"})
        high_events = tmp_db.get_events(severity="HIGH")
        assert len(high_events) == 1
        assert high_events[0]["severity"] == "HIGH"

    def test_behaviour_counts(self, tmp_db):
        """Should count events by behaviour."""
        for beh in ["standing", "standing", "crouching", None]:
            tmp_db.insert_event({
                "timestamp": "2026-10-09T20:00:00",
                "incident_id": "1",
                "severity": "LOW",
                "behaviour": beh,
            })
        counts = tmp_db.get_behaviour_counts()
        assert counts.get("standing") == 2
        assert counts.get("crouching") == 1

    def test_roi_counts(self, tmp_db):
        """Should count events by ROI name."""
        for roi in ["entrance", "entrance", "parking"]:
            tmp_db.insert_event({
                "timestamp": "2026-10-09T20:00:00",
                "incident_id": "1",
                "severity": "LOW",
                "roi_name": roi,
            })
        counts = tmp_db.get_roi_counts()
        assert counts.get("entrance") == 2
        assert counts.get("parking") == 1

    def test_full_stats(self, tmp_db):
        """get_full_stats should return a comprehensive dict."""
        tmp_db.insert_event({
            "timestamp": "2026-10-09T20:00:00",
            "incident_id": "1",
            "severity": "HIGH",
            "dwell_seconds": 10.0,
        })
        stats = tmp_db.get_full_stats()
        assert "total_events" in stats
        assert "severity_counts" in stats
        assert "unique_tracks" in stats
        assert "dwell_stats" in stats
        assert "behaviour_counts" in stats
        assert "roi_counts" in stats
        assert "timeline" in stats


# ── EventDB JSONL Import Tests ───────────────────────────────────────────

class TestEventDBImport:
    """Test JSONL evidence log import."""

    def test_import_from_jsonl(self, tmp_path):
        """Should import records from a JSONL file."""
        from event_db import EventDB

        # Create a test JSONL file
        log_path = str(tmp_path / "test_log.jsonl")
        with open(log_path, 'w') as f:
            for i in range(5):
                record = {
                    "timestamp": f"2026-10-09T20:{i:02d}:00",
                    "incident_id": str(i),
                    "severity": "HIGH" if i % 2 == 0 else "LOW",
                    "reasons": ["test"],
                    "dwell_seconds": float(i * 10),
                }
                f.write(json.dumps(record) + '\n')

        db = EventDB(db_path=str(tmp_path / "test.db"))
        count = db.import_from_jsonl(log_path)
        assert count == 5
        assert db.get_event_count() == 5

    def test_import_nonexistent_file(self, tmp_path):
        """Importing from a nonexistent file should return 0."""
        from event_db import EventDB
        db = EventDB(db_path=str(tmp_path / "test.db"))
        count = db.import_from_jsonl(str(tmp_path / "nonexistent.jsonl"))
        assert count == 0


# ── Ablation Run Storage Tests ────────────────────────────────────────────

class TestAblationStorage:
    """Test ablation run result storage."""

    @pytest.fixture
    def tmp_db(self, tmp_path):
        from event_db import EventDB
        return EventDB(db_path=str(tmp_path / "test.db"))

    def test_save_and_get_ablation_run(self, tmp_db):
        """Should save and retrieve ablation run results."""
        tmp_db.save_ablation_run({
            "run_label": "baseline",
            "timestamp": "2026-10-09T20:00:00",
            "config": {"USE_TRACKING": False},
            "total_frames": 819,
            "wall_seconds": 45.0,
            "avg_fps": 18.2,
            "confirmed_intrusions": 500,
            "low_count": 300,
            "medium_count": 150,
            "high_count": 50,
            "unique_tracks": 3,
            "avg_dwell": 5.0,
            "max_dwell": 25.0,
            "notes": "Test run",
        })
        runs = tmp_db.get_ablation_runs()
        assert len(runs) == 1
        assert runs[0]["run_label"] == "baseline"
        assert runs[0]["avg_fps"] == 18.2

    def test_multiple_runs(self, tmp_db):
        """Should store multiple runs and return them in order."""
        for label in ["baseline", "tracking", "full"]:
            tmp_db.save_ablation_run({
                "run_label": label,
                "timestamp": "2026-10-09T20:00:00",
                "config": {},
            })
        runs = tmp_db.get_ablation_runs()
        assert len(runs) == 3

    def test_clear_ablation_runs(self, tmp_db):
        """Should clear all ablation results."""
        tmp_db.save_ablation_run({
            "run_label": "test",
            "timestamp": "2026-10-09T20:00:00",
            "config": {},
        })
        tmp_db.clear_ablation_runs()
        assert len(tmp_db.get_ablation_runs()) == 0

    def test_upsert_ablation_run(self, tmp_db):
        """Re-running same profile should update, not duplicate."""
        for i in range(2):
            tmp_db.save_ablation_run({
                "run_label": "baseline",
                "timestamp": "2026-10-09T20:00:00",
                "config": {},
                "avg_fps": 10.0 + i,
            })
        runs = tmp_db.get_ablation_runs()
        assert len(runs) == 1
        assert runs[0]["avg_fps"] == 11.0  # latest value


# ── Ablation Profiles Tests ──────────────────────────────────────────────

class TestAblationProfiles:
    """Test ablation profile definitions."""

    def test_profiles_exist(self):
        """All expected profiles should be defined."""
        from ablation import PROFILES
        expected = ["baseline", "foot_only", "conf_only", "foot_conf",
                    "temporal", "tracking", "full"]
        for name in expected:
            assert name in PROFILES, f"Missing profile: {name}"

    def test_profiles_have_flags(self):
        """Each profile should define all feature flags."""
        from ablation import PROFILES
        required_flags = [
            "USE_FOOT_POINT", "USE_CONF_THRESHOLD",
            "USE_TEMPORAL_CONFIRMATION", "USE_TRACKING", "USE_POSE"
        ]
        for name, prof in PROFILES.items():
            for flag in required_flags:
                assert flag in prof["flags"], \
                    f"Profile {name} missing flag: {flag}"

    def test_baseline_all_off(self):
        """Baseline profile should have all features off."""
        from ablation import PROFILES
        for flag, value in PROFILES["baseline"]["flags"].items():
            assert value is False, \
                f"Baseline should have {flag}=False"

    def test_full_all_on(self):
        """Full profile should have all features on."""
        from ablation import PROFILES
        for flag, value in PROFILES["full"]["flags"].items():
            assert value is True, \
                f"Full profile should have {flag}=True"

    def test_profiles_have_descriptions(self):
        """Each profile should have a description."""
        from ablation import PROFILES
        for name, prof in PROFILES.items():
            assert "description" in prof and len(prof["description"]) > 0, \
                f"Profile {name} missing description"

    def test_markdown_report_generation(self):
        """Should generate a markdown report string."""
        from ablation import generate_markdown_report
        from event_db import EventDB
        import tempfile
        db = EventDB(db_path=os.path.join(tempfile.mkdtemp(), "test.db"))
        report = generate_markdown_report(db)
        assert isinstance(report, str)


# ── Dashboard Tests ──────────────────────────────────────────────────────

class TestDashboard:
    """Test dashboard API endpoints."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create a Flask test client with a temporary database."""
        from event_db import EventDB

        # Monkey-patch config for test isolation
        original_db = config.DB_PATH
        original_log = config.EVIDENCE_LOG_PATH
        config.DB_PATH = str(tmp_path / "test.db")
        config.EVIDENCE_LOG_PATH = str(tmp_path / "test_log.jsonl")

        import dashboard
        dashboard.db = EventDB(db_path=config.DB_PATH)
        dashboard.app.config['TESTING'] = True

        # Add some test data
        for i in range(10):
            dashboard.db.insert_event({
                "timestamp": f"2026-10-09T20:{i:02d}:00",
                "incident_id": str(i % 3),
                "severity": ["LOW", "MEDIUM", "HIGH"][i % 3],
                "dwell_seconds": float(i * 5),
                "behaviour": ["standing", "crouching", None][i % 3],
                "roi_name": "entrance",
            })

        with dashboard.app.test_client() as client:
            yield client

        config.DB_PATH = original_db
        config.EVIDENCE_LOG_PATH = original_log

    def test_index_page(self, client):
        """Dashboard index should return HTML."""
        rv = client.get('/')
        assert rv.status_code == 200
        assert b'ROI Surveillance Dashboard' in rv.data

    def test_api_stats(self, client):
        """Stats endpoint should return statistics."""
        rv = client.get('/api/stats')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert "total_events" in data
        assert data["total_events"] == 10

    def test_api_events(self, client):
        """Events endpoint should return event list."""
        rv = client.get('/api/events?limit=5')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert len(data) == 5

    def test_api_events_filter(self, client):
        """Events endpoint should filter by severity."""
        rv = client.get('/api/events?severity=HIGH')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert all(e["severity"] == "HIGH" for e in data)

    def test_api_config(self, client):
        """Config endpoint should return configuration."""
        rv = client.get('/api/config')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert "USE_TRACKING" in data
        assert "USE_FOOT_POINT" in data

    def test_api_chain_verify(self, client):
        """Chain verify endpoint should return status."""
        rv = client.get('/api/chain/verify')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert "valid" in data
        assert "record_count" in data

    def test_api_ablation(self, client):
        """Ablation endpoint should return results."""
        rv = client.get('/api/ablation')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert isinstance(data, list)

    def test_api_photos(self, client):
        """Photos endpoint should return list."""
        rv = client.get('/api/photos')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert isinstance(data, list)


# ── Config Phase 6 Tests ─────────────────────────────────────────────────

class TestPhase6Config:
    """Test Phase 6 config values."""

    def test_db_path_exists(self):
        assert hasattr(config, 'DB_PATH')
        assert isinstance(config.DB_PATH, str)

    def test_evidence_dir(self):
        assert hasattr(config, 'EVIDENCE_DIR')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
