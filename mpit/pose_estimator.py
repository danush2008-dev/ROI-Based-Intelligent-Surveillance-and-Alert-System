"""
pose_estimator.py — MediaPipe Pose behaviour classification.

Classifies each detected person's pose into one of:
  - 'standing'   : upright, normal
  - 'crouching'  : bent low (e.g. hiding, tampering)
  - 'lying'      : horizontal on the ground (fallen / incapacitated)
  - 'unknown'    : not enough landmarks visible

Uses MediaPipe Pose (Lite model) on the cropped person bounding box for
CPU-efficient inference.  Runs every POSE_EVERY_N_FRAMES to save CPU.

Classification heuristics:
  1. Lying: torso angle from vertical > LYING_TORSO_ANGLE  OR
            bbox width/height > LYING_ASPECT_RATIO
  2. Crouching: hip-to-ankle distance / shoulder-to-hip distance < CROUCH_HIP_RATIO
  3. Standing: default if not lying or crouching
"""

import math
import numpy as np
import cv2

try:
    import mediapipe as mp
    _HAS_MEDIAPIPE = True
except ImportError:
    _HAS_MEDIAPIPE = False

import config


class PoseEstimator:
    """
    MediaPipe Pose wrapper for behaviour classification.

    Call classify(frame, x1, y1, x2, y2) for each detected person.
    Returns (behaviour_str, landmarks_or_None).
    """

    def __init__(self):
        self._enabled = config.USE_POSE and _HAS_MEDIAPIPE
        self._pose = None

        if self._enabled:
            self._mp_pose = mp.solutions.pose
            self._pose = self._mp_pose.Pose(
                static_image_mode=False,
                model_complexity=0,        # 0 = Lite (fastest, CPU-friendly)
                smooth_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._mp_draw = mp.solutions.drawing_utils
            self._mp_draw_styles = mp.solutions.drawing_styles
            print("[Pose] MediaPipe Pose (Lite) initialized.")
        else:
            if config.USE_POSE and not _HAS_MEDIAPIPE:
                print("[Pose] WARNING: USE_POSE=True but mediapipe not installed.")
            else:
                print("[Pose] Pose estimation disabled.")

    @property
    def enabled(self):
        return self._enabled

    def classify(self, frame, x1, y1, x2, y2):
        """
        Classify the pose of a person within the given bounding box.

        Args:
            frame: full video frame (BGR)
            x1, y1, x2, y2: bounding box of the person

        Returns:
            (behaviour: str, landmarks: list or None)
            behaviour is one of: 'standing', 'crouching', 'lying', 'unknown'
            landmarks is a list of (x, y, visibility) tuples in frame coords,
            or None if pose detection failed.
        """
        if not self._enabled:
            return 'unknown', None

        h, w = frame.shape[:2]

        # Clamp bbox to frame bounds
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)

        bw = x2 - x1
        bh = y2 - y1
        if bw < 20 or bh < 20:
            return 'unknown', None

        # Crop person region with small padding
        pad = 10
        cx1 = max(0, x1 - pad)
        cy1 = max(0, y1 - pad)
        cx2 = min(w, x2 + pad)
        cy2 = min(h, y2 + pad)
        crop = frame[cy1:cy2, cx1:cx2]

        # MediaPipe expects RGB
        rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        results = self._pose.process(rgb_crop)

        if not results.pose_landmarks:
            # Fallback: use aspect ratio heuristic
            aspect = bw / bh if bh > 0 else 0
            if aspect > config.LYING_ASPECT_RATIO:
                return 'lying', None
            return 'unknown', None

        # Extract landmarks in frame coordinates
        landmarks_frame = []
        ch, cw = crop.shape[:2]
        lm = results.pose_landmarks.landmark

        for l in lm:
            fx = int(l.x * cw + cx1)
            fy = int(l.y * ch + cy1)
            landmarks_frame.append((fx, fy, l.visibility))

        # ── Classification logic ──────────────────────────────────────────

        behaviour = self._classify_from_landmarks(lm, bw, bh)

        return behaviour, landmarks_frame

    def _classify_from_landmarks(self, landmarks, bbox_w, bbox_h):
        """
        Determine pose behaviour from MediaPipe landmarks.

        Uses the PoseLandmark enum indices:
          11: LEFT_SHOULDER, 12: RIGHT_SHOULDER
          23: LEFT_HIP, 24: RIGHT_HIP
          27: LEFT_ANKLE, 28: RIGHT_ANKLE
        """
        lm = landmarks

        # Get key landmarks with visibility check
        def get_lm(idx):
            l = lm[idx]
            if l.visibility < 0.4:
                return None
            return (l.x, l.y)

        l_shoulder = get_lm(11)
        r_shoulder = get_lm(12)
        l_hip = get_lm(23)
        r_hip = get_lm(24)
        l_ankle = get_lm(27)
        r_ankle = get_lm(28)

        # Need at least shoulders and hips for classification
        shoulders = [p for p in [l_shoulder, r_shoulder] if p is not None]
        hips = [p for p in [l_hip, r_hip] if p is not None]
        ankles = [p for p in [l_ankle, r_ankle] if p is not None]

        if len(shoulders) < 1 or len(hips) < 1:
            # Not enough landmarks — use aspect ratio fallback
            aspect = bbox_w / bbox_h if bbox_h > 0 else 0
            if aspect > config.LYING_ASPECT_RATIO:
                return 'lying'
            return 'unknown'

        # Average positions
        shoulder_mid = (
            sum(p[0] for p in shoulders) / len(shoulders),
            sum(p[1] for p in shoulders) / len(shoulders),
        )
        hip_mid = (
            sum(p[0] for p in hips) / len(hips),
            sum(p[1] for p in hips) / len(hips),
        )

        # ── Check 1: Lying (torso angle from vertical) ────────────────────
        dx = hip_mid[0] - shoulder_mid[0]
        dy = hip_mid[1] - shoulder_mid[1]
        # Angle of torso from vertical (0° = upright, 90° = horizontal)
        torso_angle = abs(math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6)))

        if torso_angle > config.LYING_TORSO_ANGLE:
            return 'lying'

        # Also check bbox aspect ratio as a backup
        aspect = bbox_w / bbox_h if bbox_h > 0 else 0
        if aspect > config.LYING_ASPECT_RATIO:
            return 'lying'

        # ── Check 2: Crouching (hip-to-ankle vs shoulder-to-hip ratio) ────
        if len(ankles) >= 1:
            ankle_mid = (
                sum(p[0] for p in ankles) / len(ankles),
                sum(p[1] for p in ankles) / len(ankles),
            )
            # Distances in normalized coordinates
            torso_len = math.hypot(
                hip_mid[0] - shoulder_mid[0],
                hip_mid[1] - shoulder_mid[1]
            )
            hip_ankle_len = math.hypot(
                ankle_mid[0] - hip_mid[0],
                ankle_mid[1] - hip_mid[1]
            )

            if torso_len > 0.01:
                ratio = hip_ankle_len / torso_len
                if ratio < config.CROUCH_HIP_RATIO:
                    return 'crouching'

        # ── Default: standing ──────────────────────────────────────────────
        return 'standing'

    def draw_landmarks(self, frame, landmarks, colour=(0, 255, 0)):
        """
        Draw pose skeleton on the frame.

        Args:
            frame: video frame to draw on
            landmarks: list of (x, y, visibility) tuples
            colour: BGR colour for the skeleton
        """
        if not landmarks:
            return

        # Key connections for a simplified skeleton
        connections = [
            (11, 12),  # shoulders
            (11, 13), (13, 15),  # left arm
            (12, 14), (14, 16),  # right arm
            (11, 23), (12, 24),  # torso sides
            (23, 24),  # hips
            (23, 25), (25, 27),  # left leg
            (24, 26), (26, 28),  # right leg
        ]

        # Draw connections
        for i, j in connections:
            if i < len(landmarks) and j < len(landmarks):
                x1, y1, v1 = landmarks[i]
                x2, y2, v2 = landmarks[j]
                if v1 > 0.3 and v2 > 0.3:
                    cv2.line(frame, (x1, y1), (x2, y2), colour, 1)

        # Draw key landmark dots
        for idx in [11, 12, 23, 24, 27, 28]:  # shoulders, hips, ankles
            if idx < len(landmarks):
                x, y, v = landmarks[idx]
                if v > 0.3:
                    cv2.circle(frame, (x, y), 3, colour, -1)

    def release(self):
        """Release MediaPipe resources."""
        if self._pose is not None:
            self._pose.close()
            self._pose = None
