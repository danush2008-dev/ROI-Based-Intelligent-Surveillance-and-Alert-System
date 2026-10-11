"""
test_phase3.py — Unit tests for Phase 3: tracking, dwell time, severity.

Tests:
  - Dwell time with grace period
  - Time-window logic across midnight
  - Severity rules (LOW → MEDIUM → HIGH)
  - Severity escalation detection
"""

import sys
import os
from datetime import time as dtime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import config
from tracker import DwellTracker
from severity import (
    compute_severity, is_restricted_hours, severity_escalated,
    should_send_email, should_play_alarm, should_save_clip,
    LOW, MEDIUM, HIGH,
)


# ═══════════════════════════════════════════════════════════════════════════
# Dwell Time Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDwellTracker:
    """Test per-ID dwell time with grace period."""

    def test_initial_dwell_zero(self):
        """New track has zero dwell time."""
        dt = DwellTracker(grace_seconds=2.0)
        assert dt.get_dwell(1, "Zone 1") == 0.0

    def test_dwell_accumulates(self):
        """Dwell time should accumulate while in ROI."""
        dt = DwellTracker(grace_seconds=2.0)
        dt.update(1, "Zone 1", True, 0.0)   # enter at t=0
        dt.update(1, "Zone 1", True, 5.0)   # still in at t=5
        assert dt.get_dwell(1, "Zone 1") == pytest.approx(5.0)

    def test_dwell_stops_outside(self):
        """Dwell should stop accumulating once outside ROI (past grace)."""
        dt = DwellTracker(grace_seconds=1.0)
        dt.update(1, "Zone 1", True, 0.0)
        dt.update(1, "Zone 1", True, 5.0)
        # Leave ROI at t=5, check at t=10 (well past grace)
        result = dt.update(1, "Zone 1", False, 10.0)
        assert result == 0.0  # timer reset after grace expired

    def test_grace_period_preserves_dwell(self):
        """Brief dropout within grace should not reset dwell."""
        dt = DwellTracker(grace_seconds=3.0)
        dt.update(1, "Zone 1", True, 0.0)
        dt.update(1, "Zone 1", True, 5.0)
        # Brief dropout at t=6 (within 3s grace)
        result = dt.update(1, "Zone 1", False, 6.0)
        assert result == pytest.approx(5.0)  # preserved via grace
        # Re-enter at t=7
        dt.update(1, "Zone 1", True, 7.0)
        dt.update(1, "Zone 1", True, 10.0)
        assert dt.get_dwell(1, "Zone 1") == pytest.approx(10.0)

    def test_grace_period_expires(self):
        """After grace period expires, dwell timer resets start but accumulates."""
        dt = DwellTracker(grace_seconds=2.0)
        dt.update(1, "Zone 1", True, 0.0)
        dt.update(1, "Zone 1", True, 5.0)    # 5s dwell
        dt.update(1, "Zone 1", False, 10.0)  # left at t=5, now t=10 (5s gap > 2s grace)
        # Grace expired, accumulated = 5s, start reset
        # Re-enter
        dt.update(1, "Zone 1", True, 12.0)
        dt.update(1, "Zone 1", True, 15.0)
        # accumulated=5 + new stretch=3 = 8
        assert dt.get_dwell(1, "Zone 1") == pytest.approx(8.0)

    def test_different_tracks_independent(self):
        """Different track IDs should have independent dwell times."""
        dt = DwellTracker(grace_seconds=2.0)
        dt.update(1, "Zone 1", True, 0.0)
        dt.update(1, "Zone 1", True, 10.0)
        dt.update(2, "Zone 1", True, 5.0)
        dt.update(2, "Zone 1", True, 8.0)
        assert dt.get_dwell(1, "Zone 1") == pytest.approx(10.0)
        assert dt.get_dwell(2, "Zone 1") == pytest.approx(3.0)

    def test_different_rois_independent(self):
        """Same track in different ROIs should track independently."""
        dt = DwellTracker(grace_seconds=2.0)
        dt.update(1, "Zone A", True, 0.0)
        dt.update(1, "Zone A", True, 10.0)
        dt.update(1, "Zone B", True, 5.0)
        dt.update(1, "Zone B", True, 7.0)
        assert dt.get_dwell(1, "Zone A") == pytest.approx(10.0)
        assert dt.get_dwell(1, "Zone B") == pytest.approx(2.0)

    def test_reset_track(self):
        """Resetting a track should clear all its dwell data."""
        dt = DwellTracker(grace_seconds=2.0)
        dt.update(1, "Zone 1", True, 0.0)
        dt.update(1, "Zone 1", True, 10.0)
        dt.reset_track(1)
        assert dt.get_dwell(1, "Zone 1") == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Time-based Restriction Tests (including midnight crossing)
# ═══════════════════════════════════════════════════════════════════════════

class TestTimeRestrictions:
    """Test restricted hours logic, including midnight crossing."""

    def test_no_restriction(self):
        """ROI without restricted_hours should never be restricted."""
        roi = {"name": "Zone 1", "points": [], "restricted_hours": None}
        restricted, reason = is_restricted_hours(roi)
        assert restricted is False

    def test_normal_range_inside(self):
        """Time within a normal range (same day) should be restricted."""
        roi = {"restricted_hours": ["08:00", "17:00"]}
        # Simulate 12:00
        restricted, reason = is_restricted_hours(roi, dtime(12, 0))
        assert restricted is True
        assert "restricted_hours" in reason

    def test_normal_range_outside(self):
        """Time outside a normal range should not be restricted."""
        roi = {"restricted_hours": ["08:00", "17:00"]}
        restricted, _ = is_restricted_hours(roi, dtime(20, 0))
        assert restricted is False

    def test_midnight_crossing_night_time(self):
        """Time at night in a range crossing midnight should be restricted."""
        roi = {"restricted_hours": ["18:00", "06:00"]}
        # 22:00 should be restricted (between 18:00 and 06:00)
        restricted, _ = is_restricted_hours(roi, dtime(22, 0))
        assert restricted is True

    def test_midnight_crossing_early_morning(self):
        """Early morning in a range crossing midnight should be restricted."""
        roi = {"restricted_hours": ["18:00", "06:00"]}
        # 03:00 should be restricted
        restricted, _ = is_restricted_hours(roi, dtime(3, 0))
        assert restricted is True

    def test_midnight_crossing_daytime(self):
        """Daytime in a range crossing midnight should NOT be restricted."""
        roi = {"restricted_hours": ["18:00", "06:00"]}
        # 12:00 should NOT be restricted
        restricted, _ = is_restricted_hours(roi, dtime(12, 0))
        assert restricted is False

    def test_midnight_crossing_boundary(self):
        """Boundary times should be correctly classified."""
        roi = {"restricted_hours": ["18:00", "06:00"]}
        # 18:00 (start) should be restricted
        restricted, _ = is_restricted_hours(roi, dtime(18, 0))
        assert restricted is True
        # 06:00 (end) should be restricted
        restricted, _ = is_restricted_hours(roi, dtime(6, 0))
        assert restricted is True


# ═══════════════════════════════════════════════════════════════════════════
# Severity Rules Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSeverity:
    """Test severity scoring rules."""

    def test_low_severity_default(self):
        """Confirmed person with short dwell → LOW."""
        sev, reasons = compute_severity(dwell_seconds=3.0, person_count_in_roi=1)
        assert sev == LOW
        assert "confirmed_in_roi" in reasons

    def test_medium_severity_dwell(self):
        """Dwell >= LOW_TO_MEDIUM_SECONDS → MEDIUM."""
        sev, reasons = compute_severity(
            dwell_seconds=config.LOW_TO_MEDIUM_SECONDS,
            person_count_in_roi=1,
        )
        assert sev == MEDIUM
        assert any("dwell" in r for r in reasons)

    def test_high_severity_long_dwell(self):
        """Dwell >= MEDIUM_TO_HIGH_SECONDS → HIGH."""
        sev, reasons = compute_severity(
            dwell_seconds=config.MEDIUM_TO_HIGH_SECONDS,
            person_count_in_roi=1,
        )
        assert sev == HIGH

    def test_high_severity_multiple_persons(self):
        """Multiple persons in ROI → HIGH."""
        sev, reasons = compute_severity(
            dwell_seconds=1.0,
            person_count_in_roi=config.HIGH_PERSON_COUNT,
        )
        assert sev == HIGH
        assert any("persons_in_roi" in r for r in reasons)

    def test_high_severity_suspicious_pose(self):
        """Suspicious behavior → HIGH."""
        sev, reasons = compute_severity(
            dwell_seconds=1.0,
            person_count_in_roi=1,
            behavior="crouching",
        )
        assert sev == HIGH
        assert any("pose:crouching" in r for r in reasons)

    def test_medium_from_restricted_hours(self):
        """Restricted hours alone → MEDIUM."""
        roi = {"restricted_hours": ["18:00", "06:00"], "sensitivity": 1.0}
        sev, reasons = compute_severity(
            dwell_seconds=1.0,
            person_count_in_roi=1,
            roi=roi,
            current_time=dtime(22, 0),
        )
        assert sev == MEDIUM
        assert any("restricted_hours" in r for r in reasons)

    def test_high_from_restricted_plus_dwell(self):
        """Restricted hours + medium dwell → HIGH."""
        roi = {"restricted_hours": ["18:00", "06:00"], "sensitivity": 1.0}
        sev, reasons = compute_severity(
            dwell_seconds=config.LOW_TO_MEDIUM_SECONDS,
            person_count_in_roi=1,
            roi=roi,
            current_time=dtime(22, 0),
        )
        assert sev == HIGH

    def test_sensitivity_weight(self):
        """Higher sensitivity should amplify dwell time effect."""
        roi = {"restricted_hours": None, "sensitivity": 2.0}
        # 6s actual dwell × 2.0 sensitivity = 12s effective → MEDIUM
        sev, _ = compute_severity(
            dwell_seconds=6.0,
            person_count_in_roi=1,
            roi=roi,
        )
        assert sev == MEDIUM  # 6 * 2.0 = 12 >= LOW_TO_MEDIUM_SECONDS(10)


class TestSeverityEscalation:
    """Test severity escalation detection."""

    def test_low_to_medium(self):
        assert severity_escalated(LOW, MEDIUM) is True

    def test_medium_to_high(self):
        assert severity_escalated(MEDIUM, HIGH) is True

    def test_low_to_high(self):
        assert severity_escalated(LOW, HIGH) is True

    def test_same_level(self):
        assert severity_escalated(MEDIUM, MEDIUM) is False

    def test_decrease(self):
        assert severity_escalated(HIGH, LOW) is False


class TestSeverityActions:
    """Test which actions are gated by severity level."""

    def test_low_no_email(self):
        assert should_send_email(LOW) is False

    def test_low_no_alarm(self):
        assert should_play_alarm(LOW) is False

    def test_medium_email_yes(self):
        assert should_send_email(MEDIUM) is True

    def test_medium_alarm_no(self):
        assert should_play_alarm(MEDIUM) is False

    def test_high_email_yes(self):
        assert should_send_email(HIGH) is True

    def test_high_alarm_yes(self):
        assert should_play_alarm(HIGH) is True

    def test_high_clip_yes(self):
        assert should_save_clip(HIGH) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
