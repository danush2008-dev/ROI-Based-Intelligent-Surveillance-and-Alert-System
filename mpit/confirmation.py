"""
confirmation.py — N-of-M temporal confirmation for intrusion detection.

A person is considered a *confirmed* intruder only if they were detected
inside the ROI in at least N of the last M frames.  This dramatically
reduces false positives from single-frame misdetections.

Two modes:
  1. **With tracking** (Phase 3): uses persistent track IDs from ByteTrack.
  2. **Without tracking** (Phase 2 fallback): uses position-based matching.
     Detections within POSITION_MATCH_DIST pixels of a previous detection
     are considered the same "entity" and share a confirmation history.
"""

import math
from collections import defaultdict, deque

import config


# Maximum pixel distance for position-based matching when tracking is off.
POSITION_MATCH_DIST = 80


class TemporalConfirmer:
    """
    Tracks N-of-M temporal confirmation per entity.

    Each entity (identified by track_id or matched position) maintains a
    sliding window of M boolean values indicating whether it was inside the
    ROI in each of the last M frames.  It is "confirmed" when at least N
    of those M values are True.
    """

    def __init__(self, n=None, m=None):
        """
        Args:
            n: Number of positive frames required (default: config.TEMPORAL_N)
            m: Size of the sliding window (default: config.TEMPORAL_M)
        """
        self.n = n if n is not None else config.TEMPORAL_N
        self.m = m if m is not None else config.TEMPORAL_M
        # {entity_key: deque of booleans, maxlen=M}
        self._histories = defaultdict(lambda: deque(maxlen=self.m))
        # For position-based matching: {entity_key: (x, y)} last known position
        self._positions = {}
        # Counter for generating position-based entity keys
        self._next_pos_id = 0

    def update(self, entity_key, in_roi):
        """
        Record whether an entity was in the ROI this frame.

        Args:
            entity_key: track ID (int/str) or position-matched key
            in_roi: True if the entity is inside the ROI this frame

        Returns:
            True if the entity is confirmed (N of last M frames are True).
        """
        self._histories[entity_key].append(in_roi)
        return self.is_confirmed(entity_key)

    def is_confirmed(self, entity_key):
        """Check if entity has N positive entries in its M-frame window."""
        history = self._histories.get(entity_key)
        if history is None:
            return False
        return sum(history) >= self.n

    def get_count(self, entity_key):
        """Return (positive_count, window_size) for an entity."""
        history = self._histories.get(entity_key)
        if history is None:
            return (0, 0)
        return (sum(history), len(history))

    # ── Position-based matching (fallback when tracking is off) ────────────

    def match_by_position(self, x, y):
        """
        Find an existing entity key whose last known position is within
        POSITION_MATCH_DIST of (x, y).  If no match, create a new key.

        Args:
            x, y: Current detection position (e.g. foot point or center)

        Returns:
            entity_key (str): matched or newly created key
        """
        best_key = None
        best_dist = float('inf')

        for key, (px, py) in self._positions.items():
            dist = math.hypot(x - px, y - py)
            if dist < best_dist:
                best_dist = dist
                best_key = key

        if best_key is not None and best_dist <= POSITION_MATCH_DIST:
            # Update position
            self._positions[best_key] = (x, y)
            return best_key
        else:
            # Create new entity
            new_key = f"pos_{self._next_pos_id}"
            self._next_pos_id += 1
            self._positions[new_key] = (x, y)
            return new_key

    def mark_absent_entities(self, active_keys):
        """
        For entities NOT in active_keys this frame, record a False
        (they were not detected).  This keeps the sliding window accurate
        even when an entity temporarily disappears.

        Args:
            active_keys: set of entity keys that were detected this frame
        """
        for key in list(self._histories.keys()):
            if key not in active_keys:
                self._histories[key].append(False)

    def cleanup_stale(self, max_absent_frames=None):
        """
        Remove entities that have been absent for the entire window.
        Prevents unbounded memory growth.
        """
        max_absent = max_absent_frames or self.m
        stale_keys = []
        for key, history in self._histories.items():
            if len(history) >= max_absent and sum(history) == 0:
                stale_keys.append(key)

        for key in stale_keys:
            del self._histories[key]
            self._positions.pop(key, None)

    def reset(self):
        """Clear all entity histories (e.g. on video restart)."""
        self._histories.clear()
        self._positions.clear()
        self._next_pos_id = 0
