"""
test_phase5.py — Unit tests for Phase 5: Evidence chain, clips, privacy blurring.

Tests the hash chain integrity, clip recorder logic, privacy blurring,
and evidence manager integration — all without needing a camera or GPU.
"""

import sys
import os
import json
import hashlib
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import numpy as np
import cv2

import config


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_evidence_dir(tmp_path):
    """Create a temporary evidence directory structure."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    clips_dir = evidence_dir / "clips"
    clips_dir.mkdir()
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    return {
        "evidence_dir": str(evidence_dir),
        "clips_dir": str(clips_dir),
        "photos_dir": str(photos_dir),
        "log_path": str(evidence_dir / "evidence_log.jsonl"),
    }


@pytest.fixture
def sample_frame():
    """Create a sample BGR frame for testing."""
    return np.zeros((480, 640, 3), dtype=np.uint8) + 128  # gray frame


# ── Hash Chain Tests ──────────────────────────────────────────────────────

class TestHashChain:
    """Test the SHA-256 hash chain implementation."""

    def test_genesis_hash(self, tmp_evidence_dir):
        """First record should chain from the genesis hash."""
        from evidence import HashChain
        chain = HashChain(log_path=tmp_evidence_dir["log_path"])
        record = chain.append({"event": "test", "severity": "LOW"})

        assert record["prev_hash"] == config.GENESIS_HASH
        assert "hash" in record
        assert len(record["hash"]) == 64  # SHA-256 hex digest

    def test_chain_links(self, tmp_evidence_dir):
        """Each record's prev_hash should match the previous record's hash."""
        from evidence import HashChain
        chain = HashChain(log_path=tmp_evidence_dir["log_path"])

        r1 = chain.append({"event": "first"})
        r2 = chain.append({"event": "second"})
        r3 = chain.append({"event": "third"})

        assert r2["prev_hash"] == r1["hash"]
        assert r3["prev_hash"] == r2["hash"]

    def test_chain_verify_valid(self, tmp_evidence_dir):
        """A valid chain should pass verification."""
        from evidence import HashChain
        chain = HashChain(log_path=tmp_evidence_dir["log_path"])

        chain.append({"event": "one"})
        chain.append({"event": "two"})
        chain.append({"event": "three"})

        valid, count, err = HashChain.verify(tmp_evidence_dir["log_path"])
        assert valid is True
        assert count == 3
        assert err is None

    def test_chain_verify_tampered(self, tmp_evidence_dir):
        """Tampering with a record should break verification."""
        from evidence import HashChain
        chain = HashChain(log_path=tmp_evidence_dir["log_path"])

        chain.append({"event": "one"})
        chain.append({"event": "two"})
        chain.append({"event": "three"})

        # Tamper with the second record
        log_path = tmp_evidence_dir["log_path"]
        with open(log_path, 'r') as f:
            lines = f.readlines()

        # Modify the event field of line 2
        record = json.loads(lines[1])
        record["event"] = "TAMPERED"
        lines[1] = json.dumps(record) + '\n'

        with open(log_path, 'w') as f:
            f.writelines(lines)

        valid, count, err = HashChain.verify(log_path)
        assert valid is False
        assert err is not None
        assert "mismatch" in err.lower()

    def test_chain_verify_deleted_record(self, tmp_evidence_dir):
        """Deleting a record should break verification."""
        from evidence import HashChain
        chain = HashChain(log_path=tmp_evidence_dir["log_path"])

        chain.append({"event": "one"})
        chain.append({"event": "two"})
        chain.append({"event": "three"})

        # Delete the second record
        log_path = tmp_evidence_dir["log_path"]
        with open(log_path, 'r') as f:
            lines = f.readlines()

        # Remove line 2
        del lines[1]
        with open(log_path, 'w') as f:
            f.writelines(lines)

        valid, count, err = HashChain.verify(log_path)
        assert valid is False

    def test_chain_resume(self, tmp_evidence_dir):
        """Chain should resume from the last record's hash after restart."""
        from evidence import HashChain
        chain1 = HashChain(log_path=tmp_evidence_dir["log_path"])
        r1 = chain1.append({"event": "first"})
        r2 = chain1.append({"event": "second"})

        # Create a new chain instance (simulates restart)
        chain2 = HashChain(log_path=tmp_evidence_dir["log_path"])
        r3 = chain2.append({"event": "third"})

        # r3 should chain from r2
        assert r3["prev_hash"] == r2["hash"]

        # Full chain should verify
        valid, count, err = HashChain.verify(tmp_evidence_dir["log_path"])
        assert valid is True
        assert count == 3

    def test_empty_log_verify(self, tmp_evidence_dir):
        """Verifying an empty/nonexistent log should succeed."""
        from evidence import HashChain
        valid, count, err = HashChain.verify(tmp_evidence_dir["log_path"])
        assert valid is True
        assert count == 0

    def test_hash_deterministic(self, tmp_evidence_dir):
        """Same data should produce the same hash."""
        from evidence import HashChain
        chain = HashChain(log_path=tmp_evidence_dir["log_path"])
        data = {"event": "test", "value": 42}
        payload = json.dumps(data, sort_keys=True) + config.GENESIS_HASH
        expected = hashlib.sha256(payload.encode('utf-8')).hexdigest()

        record = chain.append(data)
        assert record["hash"] == expected


# ── Clip Recorder Tests ───────────────────────────────────────────────────

class TestClipRecorder:
    """Test pre/post event clip recording."""

    def test_buffer_fills(self, sample_frame, tmp_evidence_dir):
        """Pre-buffer should accumulate frames."""
        from evidence import ClipRecorder
        # Override clips dir
        orig_clips = config.CLIPS_DIR
        config.CLIPS_DIR = tmp_evidence_dir["clips_dir"]
        try:
            recorder = ClipRecorder(fps=10, pre_seconds=2, post_seconds=1)
            # Push 20 frames (2 seconds at 10fps)
            for _ in range(20):
                recorder.push_frame(sample_frame)
            assert not recorder.is_recording
        finally:
            config.CLIPS_DIR = orig_clips

    def test_trigger_starts_recording(self, sample_frame, tmp_evidence_dir):
        """Triggering should start recording and return a clip path."""
        from evidence import ClipRecorder
        orig_clips = config.CLIPS_DIR
        config.CLIPS_DIR = tmp_evidence_dir["clips_dir"]
        try:
            recorder = ClipRecorder(fps=10, pre_seconds=1, post_seconds=1)
            # Push pre-buffer frames
            for _ in range(10):
                recorder.push_frame(sample_frame)

            clip_path = recorder.trigger("test_incident")
            assert clip_path is not None
            assert recorder.is_recording
            assert "test_incident" in clip_path
        finally:
            recorder.release()
            config.CLIPS_DIR = orig_clips

    def test_clip_finalized_after_post_frames(self, sample_frame, tmp_evidence_dir):
        """Clip should finalize after post-buffer frames are written."""
        from evidence import ClipRecorder
        orig_clips = config.CLIPS_DIR
        config.CLIPS_DIR = tmp_evidence_dir["clips_dir"]
        try:
            recorder = ClipRecorder(fps=10, pre_seconds=1, post_seconds=1)
            # Push pre-buffer
            for _ in range(10):
                recorder.push_frame(sample_frame)

            recorder.trigger("test_done")

            # Push post-buffer frames (10 frames = 1 second at 10fps)
            finalized = None
            for _ in range(15):  # extra frames to ensure finalization
                result = recorder.push_frame(sample_frame)
                if result:
                    finalized = result
                    break

            assert finalized is not None
            assert os.path.exists(finalized)
            assert not recorder.is_recording
        finally:
            recorder.release()
            config.CLIPS_DIR = orig_clips

    def test_no_trigger_no_file(self, sample_frame, tmp_evidence_dir):
        """Without triggering, no clip file should be created."""
        from evidence import ClipRecorder
        orig_clips = config.CLIPS_DIR
        config.CLIPS_DIR = tmp_evidence_dir["clips_dir"]
        try:
            recorder = ClipRecorder(fps=10, pre_seconds=1, post_seconds=1)
            for _ in range(50):
                recorder.push_frame(sample_frame)

            clips = os.listdir(tmp_evidence_dir["clips_dir"])
            assert len(clips) == 0
        finally:
            config.CLIPS_DIR = orig_clips


# ── Privacy Blurring Tests ────────────────────────────────────────────────

class TestPrivacyBlurring:
    """Test privacy blurring for non-intruders."""

    def test_blur_when_enabled(self):
        """Non-intruder persons should be blurred when feature is on."""
        from evidence import blur_non_intruders

        orig_flag = config.BLUR_NON_INTRUDERS
        config.BLUR_NON_INTRUDERS = True
        try:
            # Use random noise so blur produces a different result
            rng = np.random.RandomState(42)
            frame = rng.randint(0, 255, (200, 300, 3), dtype=np.uint8)
            original = frame.copy()

            detections = [
                {'name': 'person', 'x1': 50, 'y1': 50, 'x2': 150, 'y2': 180,
                 'confidence': 0.9, 'track_id': 1},
                {'name': 'person', 'x1': 160, 'y1': 50, 'x2': 250, 'y2': 180,
                 'confidence': 0.85, 'track_id': 2},
            ]

            # Track 1 is intruder, track 2 is not
            result = blur_non_intruders(frame, detections, {"1"})

            # Track 2's region should be blurred (different from original)
            region_2 = result[50:180, 160:250]
            original_2 = original[50:180, 160:250]
            assert not np.array_equal(region_2, original_2), \
                "Non-intruder region should be blurred"

        finally:
            config.BLUR_NON_INTRUDERS = orig_flag

    def test_no_blur_when_disabled(self):
        """Nothing should be blurred when feature is off."""
        from evidence import blur_non_intruders

        orig_flag = config.BLUR_NON_INTRUDERS
        config.BLUR_NON_INTRUDERS = False
        try:
            frame = np.ones((200, 300, 3), dtype=np.uint8) * 100
            original = frame.copy()

            detections = [
                {'name': 'person', 'x1': 50, 'y1': 50, 'x2': 150, 'y2': 180,
                 'confidence': 0.9, 'track_id': 1},
            ]

            result = blur_non_intruders(frame, detections, set())

            assert np.array_equal(result, original), \
                "Frame should be unchanged when blurring is disabled"

        finally:
            config.BLUR_NON_INTRUDERS = orig_flag

    def test_intruder_not_blurred(self):
        """Confirmed intruders should NOT be blurred."""
        from evidence import blur_non_intruders

        orig_flag = config.BLUR_NON_INTRUDERS
        config.BLUR_NON_INTRUDERS = True
        try:
            frame = np.ones((200, 300, 3), dtype=np.uint8) * 100
            original = frame.copy()

            detections = [
                {'name': 'person', 'x1': 50, 'y1': 50, 'x2': 150, 'y2': 180,
                 'confidence': 0.9, 'track_id': 1},
            ]

            # Track 1 IS the intruder — should not be blurred
            result = blur_non_intruders(frame, detections, {"1"})

            region_1 = result[50:180, 50:150]
            original_1 = original[50:180, 50:150]
            assert np.array_equal(region_1, original_1), \
                "Intruder region should NOT be blurred"

        finally:
            config.BLUR_NON_INTRUDERS = orig_flag

    def test_vehicles_not_blurred(self):
        """Non-person classes (vehicles) should not be blurred."""
        from evidence import blur_non_intruders

        orig_flag = config.BLUR_NON_INTRUDERS
        config.BLUR_NON_INTRUDERS = True
        try:
            frame = np.ones((200, 300, 3), dtype=np.uint8) * 100
            original = frame.copy()

            detections = [
                {'name': 'car', 'x1': 50, 'y1': 50, 'x2': 150, 'y2': 180,
                 'confidence': 0.9, 'track_id': 10},
            ]

            result = blur_non_intruders(frame, detections, set())

            assert np.array_equal(result, original), \
                "Vehicles should not be blurred (only persons)"

        finally:
            config.BLUR_NON_INTRUDERS = orig_flag


# ── Evidence Manager Integration Tests ────────────────────────────────────

class TestEvidenceManager:
    """Test the EvidenceManager integration."""

    def test_save_photo_limit(self, sample_frame, tmp_evidence_dir):
        """Photo saving should respect per-incident limit."""
        from evidence import EvidenceManager
        mgr = EvidenceManager(save_dir=tmp_evidence_dir["photos_dir"])

        # Save up to limit
        for i in range(config.MAX_PHOTOS_PER_INCIDENT):
            path = mgr.save_photo(sample_frame, "incident_1")
            assert path is not None

        # Next should be None (limit reached)
        path = mgr.save_photo(sample_frame, "incident_1")
        assert path is None

    def test_different_incidents_independent(self, sample_frame, tmp_evidence_dir):
        """Different incidents should have independent photo limits."""
        from evidence import EvidenceManager
        mgr = EvidenceManager(save_dir=tmp_evidence_dir["photos_dir"])

        # Fill incident 1
        for i in range(config.MAX_PHOTOS_PER_INCIDENT):
            mgr.save_photo(sample_frame, "incident_1")

        # Incident 2 should still work
        path = mgr.save_photo(sample_frame, "incident_2")
        assert path is not None

    def test_log_event(self, tmp_evidence_dir):
        """log_event should create a valid hash-chained record."""
        from evidence import EvidenceManager, HashChain
        # Monkey-patch config for test isolation
        orig_log = config.EVIDENCE_LOG_PATH
        config.EVIDENCE_LOG_PATH = tmp_evidence_dir["log_path"]
        try:
            mgr = EvidenceManager(save_dir=tmp_evidence_dir["photos_dir"])
            record = mgr.log_event(
                incident_id="42",
                severity="HIGH",
                reasons=["dwell>=30s", "pose:crouching"],
                dwell_seconds=35.2,
                behaviour="crouching",
                roi_name="entrance",
                track_id=42,
            )

            assert record["severity"] == "HIGH"
            assert record["incident_id"] == "42"
            assert "hash" in record
            assert "prev_hash" in record
            assert record["prev_hash"] == config.GENESIS_HASH

            # Verify chain
            valid, count, err = mgr.verify_chain()
            assert valid is True
            assert count == 1
        finally:
            config.EVIDENCE_LOG_PATH = orig_log

    def test_reset_incident(self, sample_frame, tmp_evidence_dir):
        """Resetting an incident should allow new photos."""
        from evidence import EvidenceManager
        mgr = EvidenceManager(save_dir=tmp_evidence_dir["photos_dir"])

        # Fill incident
        for i in range(config.MAX_PHOTOS_PER_INCIDENT):
            mgr.save_photo(sample_frame, "incident_1")

        # Should be at limit
        assert mgr.save_photo(sample_frame, "incident_1") is None

        # Reset
        mgr.reset_incident("incident_1")
        assert mgr.get_photo_count("incident_1") == 0

        # Should work again
        path = mgr.save_photo(sample_frame, "incident_1")
        assert path is not None


# ── Config Tests ──────────────────────────────────────────────────────────

class TestPhase5Config:
    """Test Phase 5 config values exist and are sensible."""

    def test_evidence_dir(self):
        assert config.EVIDENCE_DIR == "evidence"

    def test_clips_dir(self):
        assert "clips" in config.CLIPS_DIR

    def test_evidence_log_path(self):
        assert config.EVIDENCE_LOG_PATH.endswith(".jsonl")

    def test_genesis_hash(self):
        assert len(config.GENESIS_HASH) == 64
        assert config.GENESIS_HASH == "0" * 64

    def test_clip_pre_seconds(self):
        assert config.CLIP_PRE_SECONDS > 0

    def test_clip_post_seconds(self):
        assert config.CLIP_POST_SECONDS > 0

    def test_blur_flag_exists(self):
        assert hasattr(config, 'BLUR_NON_INTRUDERS')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
