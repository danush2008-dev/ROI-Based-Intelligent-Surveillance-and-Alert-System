# ROI-Based Intelligent Surveillance and Alert System
## Comprehensive Project Review

---

## 1. Project Overview

The **ROI-Based Intelligent Surveillance and Alert System** is an end-to-end, real-time video surveillance pipeline that detects, tracks, classifies, and alerts on intrusions within user-defined Regions of Interest (ROIs). Built entirely in Python, it combines deep learning object detection (YOLOv5), skeleton-based pose estimation (MediaPipe), multi-object tracking (ByteTrack), and a multi-tier severity engine to deliver forensic-grade evidence with tamper-evident logging.

The system processes video from **live cameras or recorded files**, applies intelligent filtering to minimize false positives, and responds with graduated actions — from logging to email alerts to audible alarms — based on computed threat severity.

---

## 2. System Architecture

```
Video Source (Camera / File)
         │
         ▼
┌─────────────────┐
│    Detector      │  YOLOv5s — person, car, bus, truck
│  (detector.py)   │  Configurable confidence threshold
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   ROI Manager    │  User-drawn polygonal zones
│ (roi_manager.py) │  Foot-point or center-point check
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    Tracker       │  ByteTrack — persistent track IDs
│  (tracker.py)    │  Dwell time accumulation per-track
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Temporal       │  N-of-M sliding window confirmation
│  Confirmer       │  Eliminates transient false positives
│(confirmation.py) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Pose Estimator   │  MediaPipe Pose (Lite)
│(pose_estimator)  │  Classifies: standing, crouching,
│                  │  lying/fallen, unknown
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Severity Engine  │  LOW → MEDIUM → HIGH
│ (severity.py)    │  Based on dwell, pose, count,
│                  │  time-of-day, ROI sensitivity
└────┬────┬────┬──┘
     │    │    │
     ▼    ▼    ▼
┌────────┐┌────────┐┌──────────┐
│Evidence││ Alert  ││ Event DB │
│Manager ││ Worker ││ (SQLite) │
│(.jsonl ││(email, ││          │
│+clips) ││alarm)  ││          │
└────────┘└────────┘└────┬─────┘
                         │
                  ┌──────▼──────┐
                  │  Dashboard  │
                  │  (Flask)    │
                  └─────────────┘
```

---

## 3. Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Object Detection | YOLOv5s (PyTorch) | torch 2.4.1 |
| Pose Estimation | MediaPipe Pose Lite | 0.10.14 |
| Multi-Object Tracking | ByteTrack (via supervision) | 0.25.1 |
| Computer Vision | OpenCV | 4.11.0 |
| Web Dashboard | Flask + Chart.js | 3.1.0 |
| Database | SQLite (built-in) | — |
| Audio Alerts | pygame / winsound fallback | 2.6.1 |
| Credentials | python-dotenv (.env) | 1.1.0 |
| Testing | pytest | 8.3.3 |
| Language | Python | 3.10.11 |
| Platform | Windows (CPU) | — |

---

## 4. Feature Breakdown by Phase

### Phase 1: Foundation & Cleanup

| Feature | Description |
|---------|-------------|
| **Modular architecture** | Codebase split into 12 focused modules — each with a single responsibility |
| **Secure credentials** | Email credentials stored in `.env` file, loaded via `python-dotenv`, never committed to version control |
| **`.env.example`** | Template file showing required environment variables |
| **`.gitignore`** | Comprehensive ignore rules for venv, credentials, evidence artifacts, IDE files |
| **Background alert worker** | Email sending and alarm playback run in a daemon thread (`AlertWorker`) to never block the video loop |
| **Thread-safe queue** | Alerts dispatched via `queue.Queue` — main loop enqueues, worker dequeues and processes |
| **Audio fallback** | `pygame.mixer` → `winsound.Beep` fallback if audio device unavailable |
| **ROI persistence** | User-drawn ROIs saved to `rois.json` and auto-loaded on restart |

### Phase 2: Detection Accuracy

| Feature | Description |
|---------|-------------|
| **YOLOv5s detection** | Pre-trained YOLOv5s model detects persons, cars, buses, and trucks |
| **Configurable confidence threshold** | Detections below `CONF_THRESHOLD` (default 0.5) are filtered out |
| **Foot-point ROI check** | Uses the bottom-center of the bounding box (feet) instead of box center for more accurate ROI membership |
| **Polygonal ROI zones** | User draws arbitrary polygon regions via mouse clicks; ray-casting algorithm for point-in-polygon |
| **Interactive ROI editor** | Click-to-draw interface with visual feedback; supports multiple named ROIs |
| **N-of-M temporal confirmation** | Entity must be detected in N of the last M frames (default 8/10) before being confirmed as an intrusion |
| **Sliding window** | Temporal confirmer uses a per-entity sliding window — gaps in detection don't immediately reset the counter |
| **Stale entity cleanup** | Entities not seen for extended periods are automatically purged from the confirmer |

### Phase 3: Tracking, Dwell Time & Severity

| Feature | Description |
|---------|-------------|
| **ByteTrack multi-object tracking** | Persistent track IDs across frames via the ByteTrack algorithm (supervision library) |
| **Per-track dwell time** | Accumulated time each tracked person spends inside each ROI |
| **Grace period** | Brief tracking dropouts (≤2s) don't reset dwell time — prevents flickering |
| **Three-tier severity** | **LOW** → **MEDIUM** → **HIGH** based on configurable thresholds |
| **Dwell-based escalation** | LOW (initial) → MEDIUM (≥10s dwell) → HIGH (≥30s dwell) |
| **Person count escalation** | Automatic HIGH if ≥2 confirmed persons in a single ROI simultaneously |
| **Time-of-day restrictions** | ROIs can have restricted hours (e.g., 22:00–06:00); detections during restricted periods get severity boost |
| **Midnight crossing** | Time restrictions correctly handle ranges that cross midnight |
| **ROI sensitivity weights** | Each ROI has a configurable sensitivity multiplier (1.0–3.0) that scales dwell thresholds |
| **Severity-gated actions** | LOW = log only; MEDIUM = log + email; HIGH = log + email + alarm + video clip |
| **Severity escalation tracking** | System tracks per-track maximum severity — never downgrades, only escalates |
| **Alarm cooldown** | 5-second cooldown between alarm sounds to prevent spamming |
| **Per-track email cooldown** | Configurable cooldown (default 30s) between emails for the same track ID |

### Phase 4: Pose Estimation & Behaviour Classification

| Feature | Description |
|---------|-------------|
| **MediaPipe Pose Lite** | Full-body 33-landmark skeleton estimation on CPU |
| **Behaviour classification** | Classifies each person as: **standing**, **crouching**, **lying/fallen**, or **unknown** |
| **Crouching detection** | Hip-to-ankle vs torso ratio analysis — ratio < 0.6 = crouching |
| **Lying/fallen detection** | Dual criteria: bbox aspect ratio > 1.2 (wider than tall) OR torso angle > 45° from vertical |
| **Torso angle calculation** | Computed from shoulder midpoint to hip midpoint vector relative to vertical |
| **Suspicious pose escalation** | Crouching, lying, or fallen automatically escalates severity to HIGH |
| **CPU-optimized** | Pose runs every N-th frame (default every 3rd) to save CPU; last pose cached between runs |
| **Per-track pose caching** | Each track ID retains its last classified behaviour across frames |

### Phase 5: Evidence Chain & Forensics

| Feature | Description |
|---------|-------------|
| **SHA-256 hash chain** | Every evidence record is chained to the previous via SHA-256 — any tampering breaks the chain |
| **Tamper detection** | `verify_chain()` validates every record's hash against its content + previous hash |
| **Structured JSONL log** | Events logged to `evidence/evidence_log.jsonl` with: timestamp, incident_id, track_id, severity, reasons, dwell, behaviour, ROI, photo/clip paths, photo SHA-256 |
| **Chain resumption** | On restart, chain resumes from the last record's hash — no break between sessions |
| **Genesis hash** | First record chains from a known genesis hash (`"0"×64`) |
| **Pre/post event video clips** | Circular buffer keeps last 5 seconds of frames in memory; HIGH severity triggers: flush pre-buffer + record 5s post-event → saved as AVI |
| **Clip recording** | Clips include both pre-event context and post-event continuation |
| **Evidence photos** | Up to 3 photos per incident, with per-incident limit tracking |
| **Photo SHA-256** | Each photo file's SHA-256 hash stored in the log record for independent file integrity verification |
| **Privacy blurring** | Optional Gaussian blur of non-intruder persons in evidence photos (`BLUR_NON_INTRUDERS` flag) |
| **Intruder-only clarity** | When privacy blurring is on, confirmed intruders remain unblurred — only bystanders are anonymized |
| **Thread-safe evidence** | Hash chain and clip recorder use `threading.Lock` for concurrent access safety |

### Phase 6: Dashboard & Ablation Testing

| Feature | Description |
|---------|-------------|
| **SQLite event database** | All events stored in queryable SQLite database alongside the JSONL hash chain |
| **Dual logging** | Every event simultaneously logged to JSONL (tamper-evident) and SQLite (queryable) |
| **JSONL → SQLite import** | Dashboard auto-imports existing evidence logs on startup |
| **Web dashboard** | Beautiful dark-themed Flask dashboard at `http://localhost:5000` |
| **Overview tab** | Stats cards (total events, HIGH/MEDIUM/LOW counts, avg dwell), severity doughnut chart, event timeline, behaviour distribution, event density |
| **Events tab** | Filterable event table with severity filtering, paginated, shows time/track/severity/ROI/dwell/behaviour/reasons |
| **Evidence tab** | Photo gallery with clickable thumbnails served from `detected_photos/` |
| **Config tab** | Live display of all feature flags, thresholds, and performance settings |
| **Ablation tab** | Comparison table + FPS bar chart + stacked severity bar chart for ablation runs |
| **Hash chain status** | Real-time verification badge in dashboard header (✓ Verified / ⚠ Broken) |
| **Chart.js visualizations** | Interactive doughnut, line, and bar charts with hover tooltips |
| **Glassmorphism UI** | Modern dark theme with glass-effect cards, gradient accents, Inter font, micro-animations |
| **7 ablation profiles** | Automated testing across: baseline, foot_only, conf_only, foot_conf, temporal, tracking, full |
| **Config override CLI** | `--config-json` flag allows runtime override of any config value |
| **Ablation runner** | `ablation.py` orchestrates automated runs, collects metrics, generates comparison reports |
| **Markdown report** | Ablation results exported to `evidence/ablation_report.md` |

---

## 5. Alert System

| Alert Type | Trigger | Mechanism |
|------------|---------|-----------|
| **Evidence photo** | Any confirmed intrusion | Saved to `detected_photos/` with timestamp, limited to 3 per incident |
| **Email notification** | MEDIUM or HIGH severity | SMTP via Gmail with evidence photo attachment; per-track cooldown |
| **Audible alarm** | HIGH severity only | `pygame.mixer` alarm sound with `winsound.Beep` fallback; 5s cooldown |
| **Video clip** | HIGH severity only | Pre/post event AVI clip (5s before + 5s after trigger) |
| **Hash chain log** | Every confirmed frame | Tamper-evident JSONL record with SHA-256 chaining |
| **Database log** | Every confirmed frame | SQLite record for dashboard queries |

---

## 6. Severity Decision Matrix

| Condition | Severity | Actions |
|-----------|----------|---------|
| Person detected in ROI (initial) | **LOW** | Log only |
| Dwell ≥ 10 seconds | **MEDIUM** | Log + Email |
| Dwell ≥ 30 seconds | **HIGH** | Log + Email + Alarm + Clip |
| ≥ 2 persons in same ROI | **HIGH** | Log + Email + Alarm + Clip |
| Crouching / Lying / Fallen pose | **HIGH** | Log + Email + Alarm + Clip |
| Restricted hours + any detection | Boost to **MEDIUM** min | Log + Email |
| Restricted hours + dwell ≥ 10s | **HIGH** | Log + Email + Alarm + Clip |
| ROI sensitivity > 1.0 | Scaled thresholds | Earlier escalation |

---

## 7. Module Summary

| Module | Lines | Purpose |
|--------|-------|---------|
| [`phy.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/phy.py) | 561 | Main pipeline orchestrator — video loop, detection, tracking, severity, actions |
| [`config.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/config.py) | 90 | Central configuration — all flags, thresholds, paths, credentials |
| [`detector.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/detector.py) | ~115 | YOLOv5s model loading and inference |
| [`roi_manager.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/roi_manager.py) | ~270 | ROI drawing, persistence, point-in-polygon, foot-point calculation |
| [`tracker.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/tracker.py) | ~210 | ByteTrack wrapper + DwellTracker (per-track, per-ROI time accumulation) |
| [`confirmation.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/confirmation.py) | ~130 | N-of-M temporal confirmation with sliding window |
| [`pose_estimator.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/pose_estimator.py) | ~225 | MediaPipe pose landmark extraction + behaviour classification |
| [`severity.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/severity.py) | ~175 | Severity calculation, escalation logic, action gating |
| [`evidence.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/evidence.py) | ~430 | HashChain, ClipRecorder, blur_non_intruders, EvidenceManager |
| [`alerts.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/alerts.py) | ~210 | Background AlertWorker thread — email + alarm dispatch |
| [`event_db.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/event_db.py) | ~300 | SQLite event database with rich query API |
| [`dashboard.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/dashboard.py) | ~1185 | Flask web dashboard with embedded HTML/CSS/JS |
| [`ablation.py`](file:///D:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/ablation.py) | ~465 | Automated ablation testing framework (7 profiles) |

---

## 8. Testing

| Test File | Tests | Coverage Area |
|-----------|-------|---------------|
| `test_phase2.py` | 20 | Point-in-polygon, foot-point, temporal confirmation |
| `test_phase3.py` | 27 | Dwell tracking, time restrictions, severity calc, escalation, action gating |
| `test_phase4.py` | 14 | Pose classification heuristics, severity integration, angle calculation |
| `test_phase5.py` | 27 | Hash chain integrity, tamper detection, clip recording, privacy blurring |
| `test_phase6.py` | 39 | EventDB CRUD, JSONL import, ablation storage, dashboard API endpoints |
| **Total** | **127** | **All pass in ~5.7 seconds** |

---

## 9. Command Reference

```powershell
# ── Activate virtual environment ──────────────────────────
cd "D:\ROI-Based Intelligent Surveillance and Alert System\mpit"
.\myenv\Scripts\Activate.ps1

# ── Run surveillance pipeline ─────────────────────────────
python phy.py --source "input vedio for testing.mp4"
python phy.py --source 0                        # webcam
python phy.py --source video.mp4 --headless     # no GUI
python phy.py --source video.mp4 --dry-run      # no email/alarm
python phy.py --sim-time "22:00"                # simulate night
python phy.py --demo                            # presentation mode

# ── Launch dashboard ──────────────────────────────────────
python dashboard.py                             # http://localhost:5000
python dashboard.py --port 8080                 # custom port

# ── Run ablation tests ────────────────────────────────────
python ablation.py                              # all 7 profiles
python ablation.py --profiles baseline full     # specific profiles
python ablation.py --report                     # view past results
python ablation.py --list                       # list profiles

# ── Run unit tests ────────────────────────────────────────
python -m pytest tests/ -v                      # all 127 tests

# ── Verify evidence chain ────────────────────────────────
python -c "from evidence import HashChain; v,c,e = HashChain.verify(); print(f'Valid={v}, Records={c}')"
```

---

## 10. Key Design Decisions

1. **Modular, single-responsibility modules** — each `.py` file handles one concern, making the system testable and maintainable.

2. **Feature flags for ablation** — every enhancement (foot-point, tracking, pose, etc.) can be toggled independently in `config.py`, enabling systematic evaluation of each component's contribution.

3. **Dual evidence logging** — JSONL hash chain provides tamper-evident forensic integrity; SQLite provides fast queryable access for the dashboard. Both are written simultaneously.

4. **Non-blocking alert thread** — email sending and alarm playback run in a daemon thread with queue-based dispatch, ensuring the video loop maintains real-time frame rates.

5. **Graduated severity response** — LOW/MEDIUM/HIGH tiers prevent alert fatigue while ensuring critical events (long dwell, suspicious pose, multiple intruders) receive immediate attention.

6. **Privacy-aware evidence** — optional blurring of non-intruder persons in evidence photos supports GDPR-like compliance without compromising intruder identification.

7. **Circular clip buffer** — pre-event video context is captured without disk I/O overhead by using an in-memory `deque` as a ring buffer.

8. **Graceful degradation** — `pygame` → `winsound` audio fallback; temporal confirmation prevents false alarms; dwell grace period handles brief tracking dropouts.

---

## 11. Project Statistics

| Metric | Value |
|--------|-------|
| Total Python source files | 13 modules |
| Total lines of code | ~4,100+ |
| Unit tests | 127 (all passing) |
| Test execution time | ~5.7 seconds |
| Dependencies | 19 packages (pinned) |
| Supported classes | person, car, bus, truck |
| Severity tiers | 3 (LOW, MEDIUM, HIGH) |
| Pose classes | 4 (standing, crouching, lying, unknown) |
| Ablation profiles | 7 |
| Dashboard API endpoints | 8 |
| Evidence log records (test video) | 884 |
