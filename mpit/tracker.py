"""
tracker.py — ByteTrack wrapper + per-ID dwell time tracking.

Provides:
  - ByteTrack-based multi-object tracking via the `supervision` library
  - Per-track-ID, per-ROI dwell time with grace period
  - Conversion between YOLO detections and supervision Detections format
"""

import time
from collections import defaultdict

import numpy as np

try:
    import supervision as sv
    _HAS_SUPERVISION = True
except ImportError:
    _HAS_SUPERVISION = False
    print("[Tracker] WARNING: supervision not installed. Tracking disabled.")

import config


class DwellTracker:
    """
    Tracks how long each person (by track ID) has been inside each ROI.

    Uses video timestamps (frame position / FPS) for recorded video so
    dwell time is accurate regardless of processing speed. Falls back to
    wall-clock time for live camera feeds.

    Supports a grace period (DWELL_GRACE_SECONDS) so the timer doesn't
    reset on brief tracking dropouts (1-2 missed frames).
    """

    def __init__(self, grace_seconds=None):
        self.grace = grace_seconds if grace_seconds is not None else config.DWELL_GRACE_SECONDS
        # {(track_id, roi_name): {'start': float, 'last_seen': float, 'accumulated': float}}
        self._timers = defaultdict(lambda: {
            'start': None,
            'last_seen': None,
            'accumulated': 0.0,
        })

    def update(self, track_id, roi_name, in_roi, current_time):
        """
        Update dwell time for a track in a specific ROI.

        Args:
            track_id: persistent track ID (int)
            roi_name: name of the ROI (str)
            in_roi: whether the track is inside this ROI right now (bool)
            current_time: current video time in seconds (float)

        Returns:
            Dwell time in seconds (float). 0.0 if not in ROI.
        """
        key = (track_id, roi_name)
        timer = self._timers[key]

        if in_roi:
            if timer['start'] is None:
                # Re-entry into ROI — keep accumulated from prior stretches
                timer['start'] = current_time
                timer['last_seen'] = current_time
            else:
                timer['last_seen'] = current_time

            # Total dwell = accumulated (from previous entries) + current stretch
            return timer['accumulated'] + (current_time - timer['start'])

        else:
            # Not in ROI right now
            if timer['start'] is not None and timer['last_seen'] is not None:
                time_since_last = current_time - timer['last_seen']
                if time_since_last <= self.grace:
                    # Within grace period — don't reset yet
                    return timer['accumulated'] + (timer['last_seen'] - timer['start'])
                else:
                    # Grace period expired — accumulate and reset
                    timer['accumulated'] += (timer['last_seen'] - timer['start'])
                    timer['start'] = None
                    timer['last_seen'] = None
            return 0.0

    def get_dwell(self, track_id, roi_name):
        """Get current accumulated dwell time without updating."""
        key = (track_id, roi_name)
        timer = self._timers.get(key)
        if timer is None or timer['start'] is None:
            return timer['accumulated'] if timer else 0.0
        return timer['accumulated'] + (timer['last_seen'] - timer['start'])

    def reset_track(self, track_id):
        """Remove all dwell data for a track."""
        keys_to_remove = [k for k in self._timers if k[0] == track_id]
        for k in keys_to_remove:
            del self._timers[k]

    def reset_all(self):
        """Clear all dwell data (e.g. on video restart)."""
        self._timers.clear()


class Tracker:
    """
    ByteTrack wrapper using the supervision library.

    Converts YOLO detection dicts → supervision Detections → ByteTrack
    → enriched detection dicts with track_id field.
    """

    def __init__(self):
        self._tracker = None
        self._enabled = config.USE_TRACKING and _HAS_SUPERVISION

        if self._enabled:
            self._tracker = sv.ByteTrack(
                track_activation_threshold=0.25,
                lost_track_buffer=30,       # frames to keep lost tracks
                minimum_matching_threshold=0.8,
                frame_rate=30,              # will be updated with actual FPS
            )
            print("[Tracker] ByteTrack initialized.")
        else:
            if config.USE_TRACKING and not _HAS_SUPERVISION:
                print("[Tracker] WARNING: USE_TRACKING=True but supervision not installed.")
            print("[Tracker] Tracking disabled.")

    @property
    def enabled(self):
        return self._enabled

    def set_frame_rate(self, fps):
        """Update the tracker's frame rate (call once after opening video)."""
        if self._enabled and fps > 0:
            self._tracker.frame_rate = int(fps)

    def update(self, detections_list, frame_shape):
        """
        Run ByteTrack on a list of detection dicts.

        Args:
            detections_list: list of dicts from Detector.detect()
                             [{name, x1, y1, x2, y2, confidence}, ...]
            frame_shape: (height, width) of the frame

        Returns:
            List of enriched detection dicts with 'track_id' added.
            Detections that couldn't be tracked are dropped.
        """
        if not self._enabled or not detections_list:
            # No tracking: return detections without track_id
            return detections_list

        # Convert to numpy arrays
        n = len(detections_list)
        xyxy = np.zeros((n, 4), dtype=np.float32)
        confidences = np.zeros(n, dtype=np.float32)
        class_ids = np.zeros(n, dtype=int)

        # Build class name → class_id mapping
        class_names = list(set(d['name'] for d in detections_list))
        class_name_to_id = {name: i for i, name in enumerate(class_names)}

        for i, det in enumerate(detections_list):
            xyxy[i] = [det['x1'], det['y1'], det['x2'], det['y2']]
            confidences[i] = det['confidence']
            class_ids[i] = class_name_to_id[det['name']]

        # Create supervision Detections
        sv_detections = sv.Detections(
            xyxy=xyxy,
            confidence=confidences,
            class_id=class_ids,
        )

        # Run ByteTrack
        tracked = self._tracker.update_with_detections(sv_detections)

        # Map back to enriched dicts
        result = []
        if tracked.tracker_id is not None:
            for i in range(len(tracked)):
                # Find original detection by matching xyxy
                track_xyxy = tracked.xyxy[i]
                track_id = int(tracked.tracker_id[i])
                track_class_id = tracked.class_id[i]
                track_conf = tracked.confidence[i] if tracked.confidence is not None else 0.5

                # Reverse-map class_id to name
                class_name = class_names[track_class_id] if track_class_id < len(class_names) else "unknown"

                result.append({
                    'name': class_name,
                    'x1': int(track_xyxy[0]),
                    'y1': int(track_xyxy[1]),
                    'x2': int(track_xyxy[2]),
                    'y2': int(track_xyxy[3]),
                    'confidence': float(track_conf),
                    'track_id': track_id,
                })

        return result

    def reset(self):
        """Reset tracker state (e.g. on video restart)."""
        if self._enabled:
            self._tracker.reset()
            print("[Tracker] ByteTrack state reset.")
