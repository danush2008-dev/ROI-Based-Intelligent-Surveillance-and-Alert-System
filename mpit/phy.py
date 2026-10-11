"""
phy.py — Main entry point for ROI-Based Intelligent Surveillance System.

Pipeline:
  Video → YOLOv5 → confidence filter → foot-point ROI check → ByteTrack IDs
  → temporal confirmation → pose estimation → dwell time + severity
  → actions (log/email/alarm)

Run:
  python phy.py                                          # default video
  python phy.py --source "input vedio for testing.mp4"   # specific video
  python phy.py --source 0                               # webcam
  python phy.py --dry-run                                # no email/alarm
  python phy.py --headless                               # no GUI windows
  python phy.py --sim-time 22:00                         # simulate night
"""

import os
import sys
import json
import argparse
import warnings
from datetime import datetime

import cv2
import numpy as np

# Suppress noisy warnings before importing heavy modules
warnings.filterwarnings("ignore")

import config
from roi_manager import ROIManager
from detector import Detector
from alerts import AlertWorker
from evidence import EvidenceManager, blur_non_intruders
from confirmation import TemporalConfirmer
from tracker import Tracker, DwellTracker
from pose_estimator import PoseEstimator
from event_db import EventDB
import severity as sev


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="ROI-Based Intelligent Surveillance and Alert System"
    )
    parser.add_argument(
        "--source", type=str, default=None,
        help="Video file path or camera index (0 for webcam). "
             "Default: value from config.DEFAULT_SOURCE"
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run without GUI windows (for evaluation/server use)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Disable email sending and alarm playback."
    )
    parser.add_argument(
        "--sim-time", type=str, default=None,
        help="Simulate a time of day for testing, e.g. '22:00'."
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Enable demo mode with clean overlay for presentation recording."
    )
    parser.add_argument(
        "--config-json", type=str, default=None,
        help="JSON string of config overrides (used by ablation runner)."
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Apply CLI overrides to config ──────────────────────────────────────
    if args.sim_time:
        config.SIMULATED_TIME = args.sim_time
    if args.demo:
        config.DEMO_MODE = True

    # ── Apply JSON config overrides (ablation testing) ─────────────────────
    if args.config_json:
        try:
            overrides = json.loads(args.config_json)
            for key, value in overrides.items():
                if hasattr(config, key):
                    setattr(config, key, value)
                    print(f"[Config] Override: {key} = {value}")
        except json.JSONDecodeError as e:
            print(f"[WARNING] Invalid --config-json: {e}")

    # ── Determine video source ─────────────────────────────────────────────
    source = args.source if args.source is not None else config.DEFAULT_SOURCE
    try:
        source = int(source)
    except (ValueError, TypeError):
        pass

    # ── Open video capture ─────────────────────────────────────────────────
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open video source: {source}")
        sys.exit(1)

    ret, first_frame = cap.read()
    if not ret:
        print("[ERROR] Cannot read first frame from video source.")
        cap.release()
        sys.exit(1)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    # ── Video properties ───────────────────────────────────────────────────
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    is_live = isinstance(source, int)  # True for webcam

    # ── Preprocess helper ──────────────────────────────────────────────────
    def preprocess(img):
        height, width = img.shape[:2]
        ratio = height / width
        new_w = config.INFERENCE_SIZE
        new_h = int(new_w * ratio)
        return cv2.resize(img, (new_w, new_h))

    first_frame_resized = preprocess(first_frame)

    # ── ROI setup ──────────────────────────────────────────────────────────
    roi_mgr = ROIManager()
    loaded = roi_mgr.load()

    if not loaded and not args.headless:
        print("[INFO] No saved ROIs found. Please draw ROI(s) on the video frame.")
        roi_mgr.draw_interactive(first_frame_resized)
    elif not loaded and args.headless:
        print("[WARNING] No ROIs found and running headless — "
              "no intrusion detection will be performed.")

    roi_bounds = roi_mgr.get_combined_bounding_rect()

    # ── Initialize modules ─────────────────────────────────────────────────
    print("[INFO] Loading YOLOv5 model...")
    detector = Detector()
    print("[INFO] Model loaded.")

    alert_worker = AlertWorker(dry_run=args.dry_run)
    evidence_mgr = EvidenceManager()
    confirmer = TemporalConfirmer()
    tracker = Tracker()
    dwell_tracker = DwellTracker()
    pose_estimator = PoseEstimator()
    event_db = EventDB()

    # Set tracker frame rate
    tracker.set_frame_rate(video_fps)

    # Initialize clip recorder with actual FPS
    evidence_mgr.init_clip_recorder(video_fps)

    # ── Per-track state ────────────────────────────────────────────────────
    last_email_time = {}        # {track_id: datetime}
    track_max_severity = {}     # {track_id: severity_level}
    confirmed_intruder_ids = set()  # track IDs confirmed as intruders this frame
    track_behaviours = {}       # {incident_id: str} last known pose
    ALARM_COOLDOWN_SECONDS = 5
    last_alarm_time = None

    # ── Frame counters ─────────────────────────────────────────────────────
    frame_count = 0
    fps_start_time = datetime.now()
    fps_frame_count = 0
    display_fps = 0.0
    last_detections = []

    # ── Display ────────────────────────────────────────────────────────────
    if not args.headless:
        cv2.namedWindow('Video')
    demo_writer = None

    # ── Print startup info ─────────────────────────────────────────────────
    print(f"\n[INFO] Starting surveillance on source: {source}")
    print(f"[INFO] Headless={args.headless}, DryRun={args.dry_run}")
    print(f"[INFO] ROIs loaded: {len(roi_mgr.rois)}")
    print(f"[INFO] Tracking: {config.USE_TRACKING} (ByteTrack)")
    print(f"[INFO] Foot-point: {config.USE_FOOT_POINT}")
    print(f"[INFO] Conf threshold: {config.CONF_THRESHOLD if config.USE_CONF_THRESHOLD else 'off'}")
    print(f"[INFO] Temporal confirm: {config.USE_TEMPORAL_CONFIRMATION} "
          f"(N={config.TEMPORAL_N}, M={config.TEMPORAL_M})")
    if config.SIMULATED_TIME:
        print(f"[INFO] Simulated time: {config.SIMULATED_TIME}")
    print()

    # ═══════════════════════════════════════════════════════════════════════
    # MAIN VIDEO LOOP
    # ═══════════════════════════════════════════════════════════════════════
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Video ended or frame could not be read.")
                break

            frame_count += 1
            fps_frame_count += 1
            frame = preprocess(frame)

            # ── Compute video time (seconds from start) ───────────────────
            if is_live:
                video_time = (datetime.now() - fps_start_time).total_seconds()
            else:
                video_time = frame_count / video_fps

            # ── FPS calculation ────────────────────────────────────────────
            elapsed = (datetime.now() - fps_start_time).total_seconds()
            if elapsed >= 1.0:
                display_fps = fps_frame_count / elapsed
                fps_frame_count = 0
                fps_start_time = datetime.now()

            # ── Detection (with frame skipping) ────────────────────────────
            run_detection = (frame_count % config.DETECT_EVERY_N_FRAMES == 0)

            if run_detection and len(roi_mgr.rois) > 0:
                detections = detector.detect(frame, roi_bounds=roi_bounds)

                # ── ByteTrack tracking ─────────────────────────────────────
                if config.USE_TRACKING and tracker.enabled:
                    detections = tracker.update(detections, frame.shape[:2])

                last_detections = detections
            elif not run_detection and len(roi_mgr.rois) > 0:
                detections = last_detections
            else:
                detections = []

            # ── Push frame to clip recorder circular buffer ────────────────
            clip_done = evidence_mgr.push_frame(frame)
            if clip_done:
                print(f"[Main] Clip finalized: {clip_done}")

            # ── Per-ROI person counting ────────────────────────────────────
            # Count confirmed persons per ROI for severity calculation
            persons_per_roi = {roi['name']: 0 for roi in roi_mgr.rois}

            # ── Track active entity keys for temporal confirmation ─────────
            active_entity_keys = set()
            confirmed_intruder_ids = set()  # reset per-frame

            # ── First pass: count persons per ROI ──────────────────────────
            for det in detections:
                if det['name'] != config.INTRUSION_CLASS:
                    continue
                x1, y1, x2, y2 = det['x1'], det['y1'], det['x2'], det['y2']
                if config.USE_FOOT_POINT:
                    tp = ROIManager.get_foot_point(x1, y1, x2, y2)
                else:
                    tp = ROIManager.get_center_point(x1, y1, x2, y2)
                for roi in roi_mgr.rois:
                    if ROIManager.point_in_polygon(tp, roi["points"]):
                        persons_per_roi[roi['name']] += 1

            # ── Second pass: process each detection ────────────────────────
            for det in detections:
                name = det['name']
                x1, y1 = det['x1'], det['y1']
                x2, y2 = det['x2'], det['y2']
                conf = det['confidence']
                track_id = det.get('track_id')  # None if tracking is off

                # Determine test point
                if config.USE_FOOT_POINT and name == config.INTRUSION_CLASS:
                    test_point = ROIManager.get_foot_point(x1, y1, x2, y2)
                else:
                    test_point = ROIManager.get_center_point(x1, y1, x2, y2)

                # ── Draw bounding box (cyan for all) ───────────────────────
                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 0), 2)
                label_parts = [name]
                if config.USE_CONF_THRESHOLD:
                    label_parts.append(f"{conf:.2f}")
                if track_id is not None:
                    label_parts.append(f"ID:{track_id}")
                cv2.putText(frame, " ".join(label_parts), (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)

                # Draw test point
                if config.USE_FOOT_POINT and name == config.INTRUSION_CLASS:
                    tx, ty = test_point
                    tri_pts = np.array([
                        [tx - 6, ty - 8], [tx + 6, ty - 8], [tx, ty + 2]
                    ], dtype=np.int32)
                    cv2.fillPoly(frame, [tri_pts], (0, 165, 255))
                else:
                    cv2.circle(frame, test_point, 4, (0, 0, 255), -1)

                # ── Skip non-intrusion classes ─────────────────────────────
                if name != config.INTRUSION_CLASS and not config.ALERT_ON_VEHICLES:
                    continue

                # ── ROI check for each ROI ─────────────────────────────────
                for roi in roi_mgr.rois:
                    in_roi = ROIManager.point_in_polygon(test_point, roi["points"])

                    # ── Entity key for confirmation ────────────────────────
                    if config.USE_TRACKING and track_id is not None:
                        entity_key = f"t{track_id}"
                    else:
                        entity_key = confirmer.match_by_position(
                            test_point[0], test_point[1]
                        )
                    active_entity_keys.add(entity_key)

                    # ── Temporal confirmation ──────────────────────────────
                    if config.USE_TEMPORAL_CONFIRMATION:
                        confirmed = confirmer.update(entity_key, in_roi)
                        pos_count, _ = confirmer.get_count(entity_key)

                        if in_roi and not confirmed:
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
                            cv2.putText(frame,
                                        f"Unconfirmed ({pos_count}/{config.TEMPORAL_N})",
                                        (x1, y1 - 25),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
                            # Update dwell even when unconfirmed (for accurate timing)
                            if config.USE_TRACKING and track_id is not None:
                                dwell_tracker.update(track_id, roi['name'], in_roi, video_time)
                            continue

                        if not in_roi:
                            # Update dwell tracker with out-of-ROI state
                            if config.USE_TRACKING and track_id is not None:
                                dwell_tracker.update(track_id, roi['name'], False, video_time)
                            continue
                    else:
                        if not in_roi:
                            continue

                    # ═══════════════════════════════════════════════════════
                    # CONFIRMED INTRUSION
                    # ═══════════════════════════════════════════════════════
                    incident_id = str(track_id) if track_id is not None else entity_key

                    # ── Dwell time ─────────────────────────────────────────
                    if config.USE_TRACKING and track_id is not None:
                        dwell_s = dwell_tracker.update(
                            track_id, roi['name'], True, video_time
                        )
                    else:
                        dwell_s = 0.0

                    # ── Pose estimation (Phase 4) ──────────────────────────
                    behaviour = None
                    pose_landmarks = None
                    run_pose = (
                        config.USE_POSE
                        and pose_estimator.enabled
                        and name == config.INTRUSION_CLASS
                        and frame_count % config.POSE_EVERY_N_FRAMES == 0
                    )
                    if run_pose:
                        behaviour, pose_landmarks = pose_estimator.classify(
                            frame, x1, y1, x2, y2
                        )
                        track_behaviours[incident_id] = behaviour
                    else:
                        # Use cached behaviour from last pose frame
                        behaviour = track_behaviours.get(incident_id)

                    # ── Draw skeleton + behaviour label ────────────────────
                    if pose_landmarks:
                        pose_estimator.draw_landmarks(frame, pose_landmarks)
                    if behaviour and behaviour != 'unknown':
                        cv2.putText(frame, behaviour.upper(),
                                    (x1, y2 + 18),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                    (0, 255, 0), 1)

                    # ── Severity ───────────────────────────────────────────
                    cur_severity, reasons = sev.compute_severity(
                        dwell_seconds=dwell_s,
                        person_count_in_roi=persons_per_roi.get(roi['name'], 1),
                        behavior=behaviour,
                        roi=roi,
                    )
                    severity_color = sev.SEVERITY_COLORS.get(cur_severity, (0, 0, 255))

                    # ── Draw confirmed intruder ────────────────────────────
                    cv2.rectangle(frame, (x1, y1), (x2, y2), severity_color, 3)

                    # Build overlay label
                    overlay_parts = [cur_severity]
                    if track_id is not None:
                        overlay_parts.append(f"ID:{track_id}")
                    if dwell_s > 0:
                        overlay_parts.append(f"{dwell_s:.1f}s")
                    overlay_label = " | ".join(overlay_parts)

                    cv2.putText(frame, overlay_label,
                                (x1, y1 - 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, severity_color, 2)

                    # Top-left status
                    cv2.putText(frame, f"{cur_severity}: {', '.join(reasons)}",
                                (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                                0.6, severity_color, 2)

                    # ── Dwell time display on screen ───────────────────────
                    if dwell_s > 0:
                        cv2.putText(frame, f"Dwell: {dwell_s:.1f}s",
                                    (10, 55), cv2.FONT_HERSHEY_SIMPLEX,
                                    0.5, severity_color, 1)

                    # ── Track this as a confirmed intruder ─────────────────
                    confirmed_intruder_ids.add(incident_id)

                    # ── Privacy blurring for evidence ──────────────────────
                    evidence_frame = frame.copy()
                    evidence_frame = blur_non_intruders(
                        evidence_frame, detections, confirmed_intruder_ids
                    )

                    # ── Save evidence photo ────────────────────────────────
                    saved_path = evidence_mgr.save_photo(evidence_frame, incident_id)

                    # ── Check for severity escalation ──────────────────────
                    prev_severity = track_max_severity.get(incident_id, None)
                    escalated = (
                        prev_severity is not None
                        and sev.severity_escalated(prev_severity, cur_severity)
                    )
                    # Only store upward — never downgrade the max
                    if prev_severity is None or sev.severity_escalated(prev_severity, cur_severity):
                        track_max_severity[incident_id] = cur_severity

                    # ── Trigger clip on HIGH severity ───────────────────────
                    clip_path = None
                    if sev.should_save_clip(cur_severity):
                        clip_path = evidence_mgr.trigger_clip(incident_id)

                    # ── Log event to tamper-evident chain ──────────────────
                    log_record = evidence_mgr.log_event(
                        incident_id=incident_id,
                        severity=cur_severity,
                        reasons=reasons,
                        dwell_seconds=dwell_s,
                        behaviour=behaviour,
                        roi_name=roi['name'],
                        photo_path=saved_path,
                        clip_path=clip_path,
                        track_id=track_id,
                    )

                    # ── Log event to SQLite database ────────────────────────
                    event_db.insert_event(log_record)

                    # ── Alarm (severity-gated + cooldown) ──────────────────
                    if sev.should_play_alarm(cur_severity):
                        now_alarm = datetime.now()
                        alarm_since = (
                            (now_alarm - last_alarm_time).total_seconds()
                            if last_alarm_time is not None
                            else ALARM_COOLDOWN_SECONDS + 1
                        )
                        if alarm_since >= ALARM_COOLDOWN_SECONDS:
                            alert_worker.enqueue(alert_type="alarm")
                            last_alarm_time = now_alarm

                    # ── Email (severity-gated + per-track cooldown) ────────
                    if sev.should_send_email(cur_severity):
                        now = datetime.now()
                        last_time = last_email_time.get(incident_id)
                        seconds_since = (
                            (now - last_time).total_seconds()
                            if last_time is not None
                            else config.EMAIL_COOLDOWN_SECONDS + 1
                        )

                        # Send if cooldown expired OR severity escalated
                        if seconds_since >= config.EMAIL_COOLDOWN_SECONDS or escalated:
                            email_image = saved_path or evidence_mgr.get_latest_photo()
                            if email_image:
                                extra = (f"Severity: {cur_severity}\n"
                                         f"Reasons: {', '.join(reasons)}\n"
                                         f"Dwell: {dwell_s:.1f}s")
                                subject = f"Intruder Alert [{cur_severity}]"
                                alert_worker.enqueue(
                                    alert_type="email",
                                    image_path=email_image,
                                    subject=subject,
                                    extra_body=extra,
                                )
                                last_email_time[incident_id] = now
                                if escalated:
                                    print(f"[Main] Severity ESCALATED "
                                          f"{prev_severity}→{cur_severity} "
                                          f"for {incident_id}")

                    break  # one detection per ROI is enough

            # ── Mark absent entities ───────────────────────────────────────
            if config.USE_TEMPORAL_CONFIRMATION:
                confirmer.mark_absent_entities(active_entity_keys)
                if frame_count % 100 == 0:
                    confirmer.cleanup_stale()

            # ── Draw ROIs on frame ─────────────────────────────────────────
            if len(roi_mgr.rois) > 0:
                roi_mgr.draw_rois_on_frame(frame)

            # ── FPS overlay ────────────────────────────────────────────────
            cv2.putText(frame, f"FPS: {display_fps:.1f}",
                        (frame.shape[1] - 140, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            # ── Demo output recording ─────────────────────────────────────
            if config.DEMO_MODE:
                if demo_writer is None:
                    h, w = frame.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    demo_writer = cv2.VideoWriter(
                        config.DEMO_OUTPUT_PATH, fourcc, video_fps, (w, h)
                    )
                demo_writer.write(frame)

            # ── Display ───────────────────────────────────────────────────
            if not args.headless:
                cv2.imshow("Video", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("[INFO] Quit requested.")
                    break

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")

    # ── Cleanup ────────────────────────────────────────────────────────────
    print("[INFO] Cleaning up...")
    cap.release()
    if demo_writer is not None:
        demo_writer.release()
    evidence_mgr.release()
    if not args.headless:
        cv2.destroyAllWindows()
    alert_worker.shutdown()

    # ── Verify evidence chain on exit ──────────────────────────────────────
    valid, count, err = evidence_mgr.verify_chain()
    if count > 0:
        if valid:
            print(f"[Evidence] Hash chain verified: {count} records, integrity OK ✓")
        else:
            print(f"[Evidence] ⚠ Hash chain BROKEN: {err}")

    print("[INFO] Done.")


if __name__ == "__main__":
    main()
