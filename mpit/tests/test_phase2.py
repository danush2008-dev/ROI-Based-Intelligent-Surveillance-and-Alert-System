"""
test_phase2.py — Unit tests for Phase 2 pure-logic components.

Tests:
  - Point-in-polygon / foot-point (roi_manager.py)
  - N-of-M temporal confirmation (confirmation.py)
"""

import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import numpy as np
from roi_manager import ROIManager
from confirmation import TemporalConfirmer


# ═══════════════════════════════════════════════════════════════════════════
# ROI Manager: Point-in-polygon and foot-point tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPointInPolygon:
    """Test ROIManager.point_in_polygon and related geometry helpers."""

    # A simple square ROI: (100,100) to (300,300)
    SQUARE_ROI = [[100, 100], [300, 100], [300, 300], [100, 300]]

    def test_point_inside(self):
        """Point clearly inside the polygon should return True."""
        assert ROIManager.point_in_polygon((200, 200), self.SQUARE_ROI) is True

    def test_point_outside(self):
        """Point clearly outside the polygon should return False."""
        assert ROIManager.point_in_polygon((50, 50), self.SQUARE_ROI) is False

    def test_point_on_edge(self):
        """Point on the edge should return True (>= 0 includes boundary)."""
        assert ROIManager.point_in_polygon((100, 200), self.SQUARE_ROI) is True

    def test_point_on_corner(self):
        """Point on a corner vertex should return True."""
        assert ROIManager.point_in_polygon((100, 100), self.SQUARE_ROI) is True

    def test_point_far_outside(self):
        """Point very far from the polygon should return False."""
        assert ROIManager.point_in_polygon((1000, 1000), self.SQUARE_ROI) is False


class TestFootPoint:
    """Test foot-point (bottom-center) vs center-point calculation."""

    def test_foot_point_basic(self):
        """Foot point should be at bottom-center of bounding box."""
        # Box: (100,50) to (200,150)
        fp = ROIManager.get_foot_point(100, 50, 200, 150)
        assert fp == (150, 150)  # x=(100+200)/2=150, y=150

    def test_center_point_basic(self):
        """Center point should be at geometric center of bounding box."""
        cp = ROIManager.get_center_point(100, 50, 200, 150)
        assert cp == (150, 100)  # x=150, y=(50+150)/2=100

    def test_foot_vs_center_differ(self):
        """Foot point and center point should differ for non-zero-height box."""
        fp = ROIManager.get_foot_point(0, 0, 100, 200)
        cp = ROIManager.get_center_point(0, 0, 100, 200)
        assert fp[0] == cp[0]     # same x
        assert fp[1] > cp[1]     # foot point is lower (larger y)

    def test_foot_point_determines_roi_membership(self):
        """Foot point at bottom can be outside ROI even when center is inside."""
        # ROI at top of frame: y=0..100
        roi = [[0, 0], [400, 0], [400, 100], [0, 100]]
        # Person box tall: y=50..200 (center at y=125, foot at y=200)
        center = ROIManager.get_center_point(150, 50, 250, 200)
        foot = ROIManager.get_foot_point(150, 50, 250, 200)
        # Center (200, 125) is outside the ROI (y <= 100)
        assert ROIManager.point_in_polygon(center, roi) is False
        # Foot (200, 200) is also outside
        assert ROIManager.point_in_polygon(foot, roi) is False

        # Person box: y=0..80 (center at y=40, foot at y=80)
        center2 = ROIManager.get_center_point(150, 0, 250, 80)
        foot2 = ROIManager.get_foot_point(150, 0, 250, 80)
        # Both inside
        assert ROIManager.point_in_polygon(center2, roi) is True
        assert ROIManager.point_in_polygon(foot2, roi) is True


# ═══════════════════════════════════════════════════════════════════════════
# Temporal Confirmation: N-of-M tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTemporalConfirmation:
    """Test N-of-M temporal confirmation logic."""

    def test_immediate_not_confirmed(self):
        """A single detection should NOT be confirmed (N=8, M=10)."""
        tc = TemporalConfirmer(n=8, m=10)
        result = tc.update("track_1", True)
        assert result is False  # only 1 of 10

    def test_confirmed_after_n_frames(self):
        """After N consecutive positive frames, entity should be confirmed."""
        tc = TemporalConfirmer(n=3, m=5)
        for i in range(2):
            assert tc.update("track_1", True) is False
        # 3rd positive frame should trigger confirmation
        assert tc.update("track_1", True) is True

    def test_gap_still_confirmed_with_enough_positives(self):
        """A gap doesn't prevent confirmation if enough positives remain."""
        tc = TemporalConfirmer(n=3, m=5)
        tc.update("track_1", True)   # window: [T]         -> 1 positive
        tc.update("track_1", True)   # window: [T, T]      -> 2 positives
        tc.update("track_1", False)  # window: [T, T, F]   -> 2 positives
        tc.update("track_1", True)   # window: [T, T, F, T] -> 3 positives = n
        assert tc.is_confirmed("track_1") is True  # 3 >= n=3

    def test_gap_prevents_confirmation(self):
        """Too many gaps should prevent confirmation."""
        tc = TemporalConfirmer(n=3, m=5)
        tc.update("track_1", True)   # [T]
        tc.update("track_1", False)  # [T, F]
        tc.update("track_1", True)   # [T, F, T]     -> 2 positives
        tc.update("track_1", False)  # [T, F, T, F]  -> 2 positives
        assert tc.is_confirmed("track_1") is False  # 2 < n=3

    def test_sliding_window(self):
        """Confirmation can be lost when positive frames fall out of window."""
        tc = TemporalConfirmer(n=3, m=5)
        # Fill window: True True True False False
        tc.update("track_1", True)
        tc.update("track_1", True)
        tc.update("track_1", True)   # confirmed at 3
        assert tc.is_confirmed("track_1") is True
        tc.update("track_1", False)
        tc.update("track_1", False)  # window: [T T T F F] -> 3 positives
        assert tc.is_confirmed("track_1") is True
        tc.update("track_1", False)  # window: [T T F F F] -> 2 positives
        assert tc.is_confirmed("track_1") is False

    def test_default_n_m(self):
        """Default N=8, M=10 should require 8 positives in 10 frames."""
        tc = TemporalConfirmer()  # uses config defaults
        # Feed 7 positives -> not confirmed
        for _ in range(7):
            tc.update("track_1", True)
        assert tc.is_confirmed("track_1") is False
        # 8th positive -> confirmed
        assert tc.update("track_1", True) is True

    def test_multiple_entities_independent(self):
        """Different entities have independent confirmation histories."""
        tc = TemporalConfirmer(n=2, m=3)
        tc.update("track_1", True)
        tc.update("track_2", True)
        tc.update("track_1", True)  # track_1 confirmed
        assert tc.is_confirmed("track_1") is True
        assert tc.is_confirmed("track_2") is False
        tc.update("track_2", True)  # track_2 confirmed
        assert tc.is_confirmed("track_2") is True

    def test_mark_absent_entities(self):
        """Absent entities should get False appended to their history."""
        tc = TemporalConfirmer(n=2, m=3)
        tc.update("track_1", True)
        tc.update("track_1", True)
        assert tc.is_confirmed("track_1") is True  # 2 of 2
        # Mark track_1 as absent
        tc.mark_absent_entities(set())  # no active keys
        count, _ = tc.get_count("track_1")
        assert count == 2  # window: [T, T, F] -> 2 positives still
        tc.mark_absent_entities(set())
        count, _ = tc.get_count("track_1")
        assert count == 1  # window: [T, F, F] -> 1 positive
        assert tc.is_confirmed("track_1") is False

    def test_position_matching(self):
        """Position matching should group nearby detections together."""
        tc = TemporalConfirmer(n=2, m=5)
        key1 = tc.match_by_position(100, 200)
        key2 = tc.match_by_position(105, 205)  # within 80px -> same entity
        assert key1 == key2
        key3 = tc.match_by_position(500, 500)  # far away -> new entity
        assert key3 != key1

    def test_cleanup_stale(self):
        """Stale entities with all-False windows should be cleaned up."""
        tc = TemporalConfirmer(n=2, m=3)
        tc.update("track_1", False)
        tc.update("track_1", False)
        tc.update("track_1", False)  # window full of False
        tc.cleanup_stale()
        assert tc.get_count("track_1") == (0, 0)  # cleaned up

    def test_reset(self):
        """Reset should clear all entity histories."""
        tc = TemporalConfirmer(n=2, m=3)
        tc.update("track_1", True)
        tc.update("track_1", True)
        assert tc.is_confirmed("track_1") is True
        tc.reset()
        assert tc.is_confirmed("track_1") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
