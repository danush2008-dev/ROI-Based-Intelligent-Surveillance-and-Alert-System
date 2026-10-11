"""
severity.py — Tiered severity scoring and time-based restriction checks.

Severity levels:
  LOW    : confirmed person in ROI, short dwell, normal conditions
  MEDIUM : dwell >= LOW_TO_MEDIUM_SECONDS, OR restricted hours active
  HIGH   : dwell >= MEDIUM_TO_HIGH_SECONDS, OR 2+ people, OR suspicious pose,
           OR restricted hours + medium dwell

Returns severity level + transparent list of reasons.

Actions per level:
  LOW    -> log + save snapshot
  MEDIUM -> log + snapshot + email
  HIGH   -> log + snapshot + email + alarm + pre/post video clip
"""

from datetime import datetime, time as dtime

import config


# ── Severity levels ───────────────────────────────────────────────────────
LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"

# ── Severity colors (BGR for OpenCV) ──────────────────────────────────────
SEVERITY_COLORS = {
    LOW: (0, 255, 255),       # yellow
    MEDIUM: (0, 165, 255),    # orange
    HIGH: (0, 0, 255),        # red
}


def is_restricted_hours(roi, current_time=None):
    """
    Check if the current time falls within a ROI's restricted hours.

    Args:
        roi: ROI dict with optional 'restricted_hours' field
             e.g. ["18:00", "06:00"]  (6pm to 6am, crossing midnight)
        current_time: datetime or None (uses simulated or real time)

    Returns:
        (bool, str): (is_restricted, reason_string)
    """
    restricted = roi.get("restricted_hours")
    if not restricted or len(restricted) != 2:
        return False, ""

    # Determine current time
    if config.SIMULATED_TIME:
        try:
            parts = config.SIMULATED_TIME.split(":")
            now_time = dtime(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            now_time = datetime.now().time()
    elif current_time is not None:
        now_time = current_time if isinstance(current_time, dtime) else current_time.time()
    else:
        now_time = datetime.now().time()

    # Parse start and end times
    try:
        start_parts = restricted[0].split(":")
        end_parts = restricted[1].split(":")
        start_time = dtime(int(start_parts[0]), int(start_parts[1]))
        end_time = dtime(int(end_parts[0]), int(end_parts[1]))
    except (ValueError, IndexError):
        return False, ""

    # Handle ranges that cross midnight (e.g. 18:00 → 06:00)
    if start_time <= end_time:
        # Normal range (e.g. 08:00 → 17:00)
        is_restricted = start_time <= now_time <= end_time
    else:
        # Crosses midnight (e.g. 18:00 → 06:00)
        is_restricted = now_time >= start_time or now_time <= end_time

    if is_restricted:
        return True, f"restricted_hours({restricted[0]}-{restricted[1]})"
    return False, ""


def compute_severity(
    dwell_seconds,
    person_count_in_roi,
    behavior=None,
    roi=None,
    current_time=None,
    sensitivity=1.0,
):
    """
    Compute severity level and a transparent list of reasons.

    Args:
        dwell_seconds: how long the person has been in the ROI (float)
        person_count_in_roi: number of confirmed persons in this ROI (int)
        behavior: pose behavior string or None (e.g. "crouching", "lying")
        roi: ROI dict (for restricted_hours and sensitivity)
        current_time: datetime or None
        sensitivity: ROI sensitivity weight (default 1.0)

    Returns:
        (severity: str, reasons: list[str])
    """
    reasons = []
    severity = LOW

    # Get sensitivity from ROI if available
    if roi:
        sensitivity = roi.get("sensitivity", 1.0)

    # Effective dwell (scaled by sensitivity)
    effective_dwell = dwell_seconds * sensitivity

    # ── Check time restrictions ────────────────────────────────────────────
    restricted, restrict_reason = False, ""
    if roi:
        restricted, restrict_reason = is_restricted_hours(roi, current_time)
        if restricted:
            reasons.append(restrict_reason)

    # ── Dwell-based escalation ─────────────────────────────────────────────
    if effective_dwell >= config.MEDIUM_TO_HIGH_SECONDS:
        severity = HIGH
        reasons.append(f"dwell>={config.MEDIUM_TO_HIGH_SECONDS}s")
    elif effective_dwell >= config.LOW_TO_MEDIUM_SECONDS:
        if severity != HIGH:
            severity = MEDIUM
        reasons.append(f"dwell>={config.LOW_TO_MEDIUM_SECONDS}s")

    # ── Multi-person escalation ────────────────────────────────────────────
    if person_count_in_roi >= config.HIGH_PERSON_COUNT:
        severity = HIGH
        reasons.append(f"persons_in_roi>={config.HIGH_PERSON_COUNT}")

    # ── Behavior-based escalation ──────────────────────────────────────────
    suspicious_behaviors = {"crouching", "lying", "fallen", "climbing"}
    if behavior and behavior.lower() in suspicious_behaviors:
        if severity != HIGH:
            severity = HIGH
        reasons.append(f"pose:{behavior}")

    # ── Restricted hours escalation ────────────────────────────────────────
    if restricted:
        if severity == LOW:
            severity = MEDIUM  # restricted hours alone → MEDIUM
        if restricted and effective_dwell >= config.LOW_TO_MEDIUM_SECONDS:
            severity = HIGH  # restricted + medium dwell → HIGH
            if f"dwell>={config.LOW_TO_MEDIUM_SECONDS}s" not in reasons:
                reasons.append(f"dwell>={config.LOW_TO_MEDIUM_SECONDS}s")

    # ── Default reason for LOW ─────────────────────────────────────────────
    if not reasons:
        reasons.append("confirmed_in_roi")

    return severity, reasons


def should_send_email(severity):
    """Check if this severity level should trigger an email."""
    return severity in (MEDIUM, HIGH)


def should_play_alarm(severity):
    """Check if this severity level should trigger the alarm."""
    return severity == HIGH


def should_save_clip(severity):
    """Check if this severity level should trigger clip recording."""
    return severity == HIGH


def severity_escalated(old_severity, new_severity):
    """Check if severity has increased."""
    order = {LOW: 0, MEDIUM: 1, HIGH: 2}
    return order.get(new_severity, 0) > order.get(old_severity, 0)
