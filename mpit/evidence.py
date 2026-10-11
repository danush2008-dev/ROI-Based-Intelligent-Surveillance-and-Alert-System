"""
evidence.py — Tamper-evident evidence management.

Phase 5 features:
  - SHA-256 hash chain: every evidence record is chained to the previous,
    making any tampering detectable.
  - Structured JSONL log: each event is recorded with full metadata
    (timestamp, track ID, severity, reasons, dwell, behaviour, hash).
  - Pre/post video clips: circular frame buffer captures N seconds before
    the event; continues recording N seconds after.
  - Privacy blurring: optionally blurs non-intruder bounding boxes in
    saved evidence photos.
  - Per-incident photo limit preserved from Phase 1.
"""

import os
import json
import hashlib
import threading
from datetime import datetime
from collections import deque

import cv2
import numpy as np

import config


class HashChain:
    """
    SHA-256 hash chain for tamper-evident evidence records.

    Each record includes the hash of the previous record, forming an
    unbroken chain from the genesis hash.  If any record is modified or
    deleted, the chain breaks and verification fails.
    """

    def __init__(self, log_path=None):
        self._log_path = log_path or config.EVIDENCE_LOG_PATH
        self._prev_hash = config.GENESIS_HASH
        self._lock = threading.Lock()

        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)

        # Resume chain from last record if log exists
        self._resume_chain()

    def _resume_chain(self):
        """Read the last record's hash to continue the chain."""
        if not os.path.exists(self._log_path):
            return
        try:
            last_line = None
            with open(self._log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
            if last_line:
                record = json.loads(last_line)
                self._prev_hash = record.get("hash", config.GENESIS_HASH)
                print(f"[Evidence] Resumed hash chain from existing log "
                      f"({self._prev_hash[:16]}...)")
        except Exception as e:
            print(f"[Evidence] Warning: could not resume hash chain: {e}")

    def _compute_hash(self, record_data):
        """Compute SHA-256 hash of record data + previous hash."""
        payload = json.dumps(record_data, sort_keys=True) + self._prev_hash
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def append(self, record_data):
        """
        Append a record to the hash chain and write to the JSONL log.

        Args:
            record_data: dict with event metadata (will be augmented with
                         prev_hash, hash, and seq fields).

        Returns:
            The complete record dict including hash fields.
        """
        with self._lock:
            record = dict(record_data)
            record["prev_hash"] = self._prev_hash
            record["hash"] = self._compute_hash(record_data)
            self._prev_hash = record["hash"]

            try:
                with open(self._log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(record, default=str) + '\n')
            except Exception as e:
                print(f"[Evidence] Error writing log: {e}")

            return record

    @staticmethod
    def verify(log_path=None):
        """
        Verify the integrity of the entire hash chain.

        Returns:
            (is_valid: bool, record_count: int, error_msg: str or None)
        """
        log_path = log_path or config.EVIDENCE_LOG_PATH
        if not os.path.exists(log_path):
            return True, 0, None

        prev_hash = config.GENESIS_HASH
        count = 0

        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    count += 1
                    record = json.loads(line)

                    # Check prev_hash links to prior record
                    stored_prev = record.get("prev_hash", "")
                    if stored_prev != prev_hash:
                        return False, count, (
                            f"Line {line_no}: prev_hash mismatch. "
                            f"Expected {prev_hash[:16]}..., "
                            f"got {stored_prev[:16]}..."
                        )

                    # Recompute hash from data (exclude hash fields)
                    data = {k: v for k, v in record.items()
                            if k not in ("hash", "prev_hash")}
                    payload = json.dumps(data, sort_keys=True) + prev_hash
                    expected_hash = hashlib.sha256(
                        payload.encode('utf-8')
                    ).hexdigest()

                    stored_hash = record.get("hash", "")
                    if stored_hash != expected_hash:
                        return False, count, (
                            f"Line {line_no}: hash mismatch. "
                            f"Expected {expected_hash[:16]}..., "
                            f"got {stored_hash[:16]}..."
                        )

                    prev_hash = stored_hash

        except json.JSONDecodeError as e:
            return False, count, f"JSON parse error: {e}"
        except Exception as e:
            return False, count, f"Verification error: {e}"

        return True, count, None


class ClipRecorder:
    """
    Pre/post event video clip recorder using a circular frame buffer.

    Maintains a rolling buffer of the last N seconds of frames (pre-buffer).
    When an event triggers, the pre-buffer is flushed to disk and recording
    continues for N more seconds (post-buffer), then the clip is finalized.
    """

    def __init__(self, fps=25.0, pre_seconds=None, post_seconds=None):
        self._fps = max(1, fps)
        self._pre_seconds = pre_seconds if pre_seconds is not None else config.CLIP_PRE_SECONDS
        self._post_seconds = post_seconds if post_seconds is not None else config.CLIP_POST_SECONDS
        self._pre_buffer_size = int(self._fps * self._pre_seconds)
        self._post_frame_count = int(self._fps * self._post_seconds)

        # Circular buffer for pre-event frames
        self._buffer = deque(maxlen=max(1, self._pre_buffer_size))

        # Active clip recording state
        self._recording = False
        self._writer = None
        self._clip_path = None
        self._post_frames_remaining = 0
        self._lock = threading.Lock()

        os.makedirs(config.CLIPS_DIR, exist_ok=True)

    def push_frame(self, frame):
        """
        Push a frame into the circular buffer.
        If actively recording a clip, also write to the output file.

        Args:
            frame: BGR frame (numpy array)

        Returns:
            clip_path if a clip was just finalized, else None
        """
        with self._lock:
            if self._recording:
                # Writing post-event frames
                if self._writer is not None:
                    self._writer.write(frame)
                self._post_frames_remaining -= 1

                if self._post_frames_remaining <= 0:
                    return self._finalize_clip()
            else:
                # Buffer pre-event frames
                self._buffer.append(frame.copy())

        return None

    def trigger(self, incident_id="unknown"):
        """
        Trigger clip recording: flush pre-buffer and start post-recording.

        Args:
            incident_id: identifier for the clip filename

        Returns:
            clip_path (str) — path where the clip will be saved
        """
        with self._lock:
            if self._recording:
                # Already recording — extend the post-buffer
                self._post_frames_remaining = self._post_frame_count
                return self._clip_path

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._clip_path = os.path.join(
                config.CLIPS_DIR,
                f"clip_{incident_id}_{timestamp}.avi"
            )

            # Get frame dimensions from buffer
            if len(self._buffer) == 0:
                return None

            sample = self._buffer[0]
            h, w = sample.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            self._writer = cv2.VideoWriter(
                self._clip_path, fourcc, self._fps, (w, h)
            )

            if not self._writer.isOpened():
                print(f"[Evidence] Warning: could not open clip writer for {self._clip_path}")
                self._writer = None
                return None

            # Flush pre-buffer
            for buffered_frame in self._buffer:
                self._writer.write(buffered_frame)
            self._buffer.clear()

            self._recording = True
            self._post_frames_remaining = self._post_frame_count

            print(f"[Evidence] Clip recording started: {self._clip_path} "
                  f"(pre={self._pre_seconds}s, post={self._post_seconds}s)")

            return self._clip_path

    def _finalize_clip(self):
        """Finalize the current clip and return its path."""
        clip_path = self._clip_path
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        self._recording = False
        self._clip_path = None
        self._post_frames_remaining = 0
        print(f"[Evidence] Clip saved: {clip_path}")
        return clip_path

    @property
    def is_recording(self):
        return self._recording

    def release(self):
        """Release any open writer."""
        with self._lock:
            if self._writer is not None:
                self._writer.release()
                self._writer = None
            self._recording = False


def blur_non_intruders(frame, detections, intruder_ids):
    """
    Blur bounding boxes of persons who are NOT intruders (privacy protection).

    Args:
        frame: BGR frame (will be modified in-place)
        detections: list of detection dicts
        intruder_ids: set of track_ids (or incident_ids) that are confirmed
                      intruders — these will NOT be blurred.

    Returns:
        The modified frame.
    """
    if not config.BLUR_NON_INTRUDERS:
        return frame

    for det in detections:
        if det['name'] != config.INTRUSION_CLASS:
            continue
        track_id = det.get('track_id')
        incident_id = str(track_id) if track_id is not None else None

        # Skip intruders — they should be visible in evidence
        if incident_id and incident_id in intruder_ids:
            continue

        x1, y1 = max(0, det['x1']), max(0, det['y1'])
        x2, y2 = min(frame.shape[1], det['x2']), min(frame.shape[0], det['y2'])

        if x2 > x1 and y2 > y1:
            roi = frame[y1:y2, x1:x2]
            # Strong Gaussian blur for privacy
            ksize = max(31, (min(x2 - x1, y2 - y1) // 4) * 2 + 1)
            blurred = cv2.GaussianBlur(roi, (ksize, ksize), 30)
            frame[y1:y2, x1:x2] = blurred

    return frame


class EvidenceManager:
    """
    Manages evidence collection: photos, clips, hash chain, and logging.

    Backward-compatible with Phase 1-4 API (save_photo, get_latest_photo).
    """

    def __init__(self, save_dir=None):
        self.save_dir = save_dir or config.DETECTED_PHOTOS_DIR
        os.makedirs(self.save_dir, exist_ok=True)

        # Track photo count per incident (keyed by incident/track ID)
        self._photo_counts = {}  # {incident_id: count}

        # Hash chain for tamper-evident logging
        self._hash_chain = HashChain()

        # Clip recorder (initialized later when FPS is known)
        self._clip_recorder = None

    def init_clip_recorder(self, fps):
        """Initialize the clip recorder with the video's FPS."""
        self._clip_recorder = ClipRecorder(fps=fps)
        print(f"[Evidence] Clip recorder initialized "
              f"(pre={config.CLIP_PRE_SECONDS}s, post={config.CLIP_POST_SECONDS}s, "
              f"fps={fps:.1f})")

    def push_frame(self, frame):
        """Push a frame to the clip recorder's circular buffer."""
        if self._clip_recorder is not None:
            return self._clip_recorder.push_frame(frame)
        return None

    def save_photo(self, frame, incident_id="global"):
        """
        Save an evidence photo for the given incident.

        Args:
            frame: BGR image to save
            incident_id: unique identifier for the incident (e.g. track ID)

        Returns:
            The file path if saved, None if limit reached.
        """
        # Check per-incident limit
        count = self._photo_counts.get(incident_id, 0)
        if count >= config.MAX_PHOTOS_PER_INCIDENT:
            return None

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"detected_{timestamp}.jpg"
        file_path = os.path.join(self.save_dir, filename)

        try:
            saved = cv2.imwrite(file_path, frame)
            if saved:
                self._photo_counts[incident_id] = count + 1
                print(f"[Evidence] Saved photo: {file_path} "
                      f"(incident={incident_id}, {count+1}/{config.MAX_PHOTOS_PER_INCIDENT})")
                return file_path
            else:
                print(f"[Evidence] cv2.imwrite failed for {file_path}")
                return None
        except Exception as e:
            print(f"[Evidence] Error saving photo: {e}")
            return None

    def log_event(self, incident_id, severity, reasons, dwell_seconds,
                  behaviour=None, roi_name=None, photo_path=None,
                  clip_path=None, track_id=None):
        """
        Log an evidence event to the tamper-evident JSONL chain.

        Args:
            incident_id: unique incident identifier
            severity: severity level string
            reasons: list of reason strings
            dwell_seconds: dwell time in seconds
            behaviour: pose behaviour string or None
            roi_name: name of the ROI
            photo_path: path to saved evidence photo or None
            clip_path: path to saved video clip or None
            track_id: ByteTrack track ID or None

        Returns:
            The complete record dict with hash.
        """
        record_data = {
            "timestamp": datetime.now().isoformat(),
            "incident_id": str(incident_id),
            "track_id": track_id,
            "severity": severity,
            "reasons": reasons,
            "dwell_seconds": round(dwell_seconds, 2),
            "behaviour": behaviour,
            "roi_name": roi_name,
            "photo_path": photo_path,
            "clip_path": clip_path,
        }

        # Compute photo hash if photo exists (for tamper detection of the image itself)
        if photo_path and os.path.exists(photo_path):
            try:
                with open(photo_path, 'rb') as f:
                    record_data["photo_sha256"] = hashlib.sha256(f.read()).hexdigest()
            except Exception:
                pass

        record = self._hash_chain.append(record_data)
        return record

    def trigger_clip(self, incident_id):
        """
        Trigger pre/post video clip recording for an incident.

        Returns:
            clip_path (str) or None
        """
        if self._clip_recorder is not None:
            return self._clip_recorder.trigger(incident_id)
        return None

    @property
    def clip_recording(self):
        """Whether a clip is currently being recorded."""
        return self._clip_recorder is not None and self._clip_recorder.is_recording

    def reset_incident(self, incident_id):
        """Reset the photo count for an incident (allows new photos)."""
        self._photo_counts.pop(incident_id, None)

    def get_photo_count(self, incident_id="global"):
        """Get the current photo count for an incident."""
        return self._photo_counts.get(incident_id, 0)

    def get_latest_photo(self):
        """Return the path of the most recently saved photo, or None."""
        try:
            files = sorted(os.listdir(self.save_dir))
            if files:
                return os.path.join(self.save_dir, files[-1])
        except Exception:
            pass
        return None

    def verify_chain(self):
        """
        Verify the integrity of the evidence hash chain.

        Returns:
            (is_valid: bool, record_count: int, error_msg: str or None)
        """
        return HashChain.verify()

    def release(self):
        """Release resources (clip recorder, etc.)."""
        if self._clip_recorder is not None:
            self._clip_recorder.release()
