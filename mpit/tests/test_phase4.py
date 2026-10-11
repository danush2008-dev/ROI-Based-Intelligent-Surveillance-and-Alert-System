"""
test_phase4.py — Unit tests for Phase 4: pose classification logic.

Tests the classification heuristics independent of MediaPipe.
"""

import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import config
from severity import compute_severity, HIGH


class TestPoseClassificationHeuristics:
    """Test pose classification thresholds from config."""

    def test_lying_aspect_ratio_default(self):
        """Lying detection uses bbox width/height > 1.2."""
        assert config.LYING_ASPECT_RATIO == 1.2

    def test_crouch_ratio_default(self):
        """Crouching detection uses hip-ankle/torso ratio < 0.6."""
        assert config.CROUCH_HIP_RATIO == 0.6

    def test_lying_torso_angle_default(self):
        """Lying detection uses torso angle > 45° from vertical."""
        assert config.LYING_TORSO_ANGLE == 45

    def test_pose_every_n_frames(self):
        """Pose runs every 3rd frame by default (CPU saving)."""
        assert config.POSE_EVERY_N_FRAMES == 3


class TestPoseSeverityIntegration:
    """Test that pose behaviours correctly escalate severity."""

    def test_crouching_escalates_to_high(self):
        """Crouching behaviour should escalate to HIGH severity."""
        sev, reasons = compute_severity(
            dwell_seconds=1.0,
            person_count_in_roi=1,
            behavior="crouching",
        )
        assert sev == HIGH
        assert any("pose:crouching" in r for r in reasons)

    def test_lying_escalates_to_high(self):
        """Lying behaviour should escalate to HIGH severity."""
        sev, reasons = compute_severity(
            dwell_seconds=1.0,
            person_count_in_roi=1,
            behavior="lying",
        )
        assert sev == HIGH
        assert any("pose:lying" in r for r in reasons)

    def test_standing_does_not_escalate(self):
        """Standing behaviour should NOT change severity level."""
        sev, reasons = compute_severity(
            dwell_seconds=1.0,
            person_count_in_roi=1,
            behavior="standing",
        )
        assert sev != HIGH
        assert not any("pose:" in r for r in reasons)

    def test_unknown_does_not_escalate(self):
        """Unknown behaviour should NOT change severity level."""
        sev, reasons = compute_severity(
            dwell_seconds=1.0,
            person_count_in_roi=1,
            behavior="unknown",
        )
        assert sev != HIGH

    def test_none_behaviour_does_not_escalate(self):
        """None behaviour (pose disabled) should NOT change severity."""
        sev, reasons = compute_severity(
            dwell_seconds=1.0,
            person_count_in_roi=1,
            behavior=None,
        )
        assert sev != HIGH

    def test_fallen_escalates_to_high(self):
        """Fallen behaviour should escalate to HIGH severity."""
        sev, reasons = compute_severity(
            dwell_seconds=1.0,
            person_count_in_roi=1,
            behavior="fallen",
        )
        assert sev == HIGH


class TestPoseAngleCalculation:
    """Test torso angle calculation used in pose classification."""

    def test_upright_angle(self):
        """Upright torso (shoulders above hips) should give angle near 0."""
        # shoulder_mid = (0.5, 0.3), hip_mid = (0.5, 0.6)
        dx = 0.5 - 0.5  # 0
        dy = 0.6 - 0.3  # 0.3
        angle = abs(math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6)))
        assert angle < 10  # nearly vertical

    def test_horizontal_angle(self):
        """Horizontal torso should give angle near 90."""
        # shoulder_mid = (0.3, 0.5), hip_mid = (0.7, 0.5)
        dx = 0.7 - 0.3  # 0.4
        dy = 0.5 - 0.5  # 0
        angle = abs(math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6)))
        assert angle > 80  # nearly horizontal

    def test_diagonal_angle(self):
        """45° diagonal should give angle ~45."""
        dx = 0.3
        dy = 0.3
        angle = abs(math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6)))
        assert 40 < angle < 50  # ~45°


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
