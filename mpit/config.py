"""
config.py — Central configuration for ROI-Based Intelligent Surveillance System.

All settings, feature flags, and thresholds are defined here as module-level
constants.  Every feature can be toggled on/off for ablation testing (Phase 6).
"""

import os
from dotenv import load_dotenv

# ── Load .env for credentials ──────────────────────────────────────────────
load_dotenv()

# ── Credentials (loaded from .env) ─────────────────────────────────────────
EMAIL_SENDER       = os.getenv("EMAIL_SENDER", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")
EMAIL_RECEIVER     = os.getenv("EMAIL_RECEIVER", "")

# ── Email settings ─────────────────────────────────────────────────────────
EMAIL_COOLDOWN_SECONDS = 30          # minimum seconds between emails (per-track)

# ── Paths ──────────────────────────────────────────────────────────────────
ALARM_PATH          = "Alarm/alarm.wav"
DETECTED_PHOTOS_DIR = "detected_photos"
ROI_JSON_PATH       = "rois.json"
EVIDENCE_DIR        = "evidence"
CLIPS_DIR           = os.path.join(EVIDENCE_DIR, "clips")
EVIDENCE_LOG_PATH   = os.path.join(EVIDENCE_DIR, "evidence_log.jsonl")
DB_PATH             = "events.db"

# ── Video source ───────────────────────────────────────────────────────────
DEFAULT_SOURCE      = "input vedio for testing.mp4"

# ── Detection settings ─────────────────────────────────────────────────────
TARGET_CLASSES      = ['car', 'bus', 'truck', 'person']
INTRUSION_CLASS     = 'person'

# ── Feature flags (toggle for ablation) ────────────────────────────────────
USE_FOOT_POINT             = True     # Phase 2: bottom-center instead of box center
USE_CONF_THRESHOLD         = True     # Phase 2: filter low-confidence detections
USE_TEMPORAL_CONFIRMATION  = True     # Phase 2: N-of-M confirmation
USE_TRACKING               = True     # Phase 3: ByteTrack persistent IDs
USE_POSE                   = True     # Phase 4: MediaPipe pose classification
ENABLE_VLM                 = False    # Phase 4: VLM false-positive check (disabled)
ALERT_ON_VEHICLES          = False    # Phase 3: trigger alerts for vehicles too
BLUR_NON_INTRUDERS         = False    # Phase 5: blur non-intruders in evidence

# ── Speed / performance options ────────────────────────────────────────────
DETECT_EVERY_N_FRAMES = 1            # run detector every N-th frame (1=every frame)
INFERENCE_SIZE        = 640           # YOLO input size (416 or 640)
CROP_TO_ROI_BOUNDS    = False         # crop frame to ROI bounding rect before YOLO

# ── Confidence threshold ───────────────────────────────────────────────────
CONF_THRESHOLD = 0.5                  # ignore detections below this

# ── Temporal confirmation (N-of-M) ────────────────────────────────────────
TEMPORAL_N = 8                        # must be detected in N of last M frames
TEMPORAL_M = 10

# ── Evidence / photos ─────────────────────────────────────────────────────
MAX_PHOTOS_PER_INCIDENT = 3           # per-incident photo limit

# ── Dwell / loitering ─────────────────────────────────────────────────────
DWELL_GRACE_SECONDS = 2.0             # grace period for brief tracking dropouts

# ── Time-based restrictions ────────────────────────────────────────────────
SIMULATED_TIME = None                 # e.g. "22:00" to simulate a time of day

# ── Severity thresholds (seconds) ─────────────────────────────────────────
LOW_TO_MEDIUM_SECONDS  = 10           # dwell threshold for LOW → MEDIUM
MEDIUM_TO_HIGH_SECONDS = 30           # dwell threshold for MEDIUM → HIGH
HIGH_PERSON_COUNT      = 2            # number of people in ROI for auto-HIGH

# ── Pre/post clip buffer ──────────────────────────────────────────────────
CLIP_PRE_SECONDS  = 5                 # seconds of frames to keep before event
CLIP_POST_SECONDS = 5                 # seconds of frames to record after event

# ── Pose behavior thresholds ──────────────────────────────────────────────
POSE_EVERY_N_FRAMES    = 3            # run pose every N-th frame (CPU saving)
CROUCH_HIP_RATIO       = 0.6         # hip-to-ankle / torso ratio for "crouching"
LYING_ASPECT_RATIO     = 1.2         # bbox width/height ratio for "lying/fallen"
LYING_TORSO_ANGLE      = 45          # torso angle from vertical for "lying"

# ── Demo mode ─────────────────────────────────────────────────────────────
DEMO_MODE           = False           # clean overlay for presentation recording
DEMO_OUTPUT_PATH    = "demo_output.mp4"

# ── Hash-chain genesis ────────────────────────────────────────────────────
GENESIS_HASH = "0" * 64              # 64-char zero hash for first record
