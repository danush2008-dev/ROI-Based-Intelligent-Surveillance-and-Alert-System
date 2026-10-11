# ROI-Based Intelligent Surveillance and Alert System — Project Guide

## ✅ Code Health Status

| Check | Result |
|-------|--------|
| Syntax compilation (all 12 .py files) | ✅ Pass |
| Unit tests (127 tests across 5 test files) | ✅ All 127 passed |
| Module imports (`phy.py`, `dashboard.py`) | ✅ Pass |
| Virtual environment (Python 3.10.11) | ✅ Present at `myenv/` |
| Dependencies (`requirements.txt`) | ✅ 22 packages listed |
| Alarm sound file | ✅ `Alarm/alarm.wav` exists |
| ROI config | ✅ `rois.json` exists with Zone 1 |
| Test video | ✅ `input vedio for testing.mp4` exists |

> [!NOTE]
> **No code bugs were found.** All 12 Python source files compile cleanly, all 127 unit tests pass, and module imports work correctly. The project is functionally sound.

---

## 🚀 Commands to Run in VSCode Terminal

> [!IMPORTANT]
> All commands must be run from the project directory:
> ```
> d:\ROI-Based Intelligent Surveillance and Alert System\mpit
> ```
> Open a **new terminal** in VSCode (`Ctrl+`` `) and then navigate there:
> ```powershell
> cd "d:\ROI-Based Intelligent Surveillance and Alert System\mpit"
> ```

### Step 1: Activate the Virtual Environment

```powershell
.\myenv\Scripts\Activate.ps1
```

> [!TIP]
> If you get an "execution policy" error, run this first (one-time):
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

### Step 2: Verify Dependencies Are Installed

```powershell
pip install -r requirements.txt
```

### Step 3: Run the Unit Tests

```powershell
python -m pytest tests/ -v
```

Expected output: `127 passed`

### Step 4: Run the Main Surveillance System

```powershell
# Option A: Run with the test video (default)
python phy.py

# Option B: Run with webcam (live camera)
python phy.py --source 0

# Option C: Run in dry-run mode (no emails/alarms)
python phy.py --dry-run

# Option D: Run headless (no GUI, for testing)
python phy.py --headless --dry-run

# Option E: Simulate nighttime (restricted hours testing)
python phy.py --sim-time 22:00

# Option F: Record a demo video
python phy.py --demo
```

### Step 5: Run the Web Dashboard

```powershell
python dashboard.py
```

Then open **http://127.0.0.1:5000** in your browser.

```powershell
# Custom port:
python dashboard.py --port 8080
```

### Step 6: Run Ablation Testing

```powershell
# List available profiles
python ablation.py --list

# Run ALL ablation profiles
python ablation.py

# Run specific profiles
python ablation.py --profiles baseline full

# View previous results
python ablation.py --report

# Clear old results
python ablation.py --clear
```

---

## 📁 Project Architecture

```
mpit/
├── phy.py                  ← Main entry point (video loop + pipeline)
├── config.py               ← Central configuration / feature flags
├── detector.py             ← YOLOv5 model loading & inference
├── roi_manager.py          ← ROI drawing, save/load, point-in-polygon
├── confirmation.py         ← N-of-M temporal confirmation
├── tracker.py              ← ByteTrack multi-object tracking + dwell time
├── pose_estimator.py       ← MediaPipe pose behaviour classification
├── severity.py             ← Tiered severity scoring (LOW/MEDIUM/HIGH)
├── alerts.py               ← Background email + alarm worker
├── evidence.py             ← Hash-chain evidence, clips, privacy blur
├── event_db.py             ← SQLite event database
├── dashboard.py            ← Flask web dashboard
├── ablation.py             ← Automated ablation testing
├── requirements.txt        ← Python dependencies
├── .env                    ← Email credentials (private)
├── .env.example            ← Template for .env
├── rois.json               ← Saved ROI polygon(s)
├── yolov5s.pt              ← YOLOv5s weights (local fallback)
├── events.db               ← SQLite database
├── Alarm/alarm.wav         ← Alarm sound file
├── detected_photos/        ← Saved evidence photos
├── evidence/               ← Hash-chain logs + video clips
│   ├── evidence_log.jsonl
│   └── clips/
├── tests/                  ← Unit test suite
│   ├── test_phase2.py      ← ROI + temporal confirmation tests
│   ├── test_phase3.py      ← Severity + time restriction tests
│   ├── test_phase4.py      ← Pose estimation tests
│   ├── test_phase5.py      ← Evidence chain + clips + blur tests
│   └── test_phase6.py      ← Database + dashboard + ablation tests
└── myenv/                  ← Python 3.10.11 virtual environment
```

---

## ⚙️ Configuration

All settings are in [`config.py`](file:///d:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/config.py). Key feature flags:

| Flag | Default | Description |
|------|---------|-------------|
| `USE_FOOT_POINT` | `True` | Bottom-center instead of box center for ROI check |
| `USE_CONF_THRESHOLD` | `True` | Filter low-confidence detections |
| `USE_TEMPORAL_CONFIRMATION` | `True` | N-of-M frame confirmation |
| `USE_TRACKING` | `True` | ByteTrack persistent IDs |
| `USE_POSE` | `True` | MediaPipe pose classification |
| `BLUR_NON_INTRUDERS` | `False` | Privacy blur in evidence photos |

Email credentials are loaded from [`.env`](file:///d:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/.env) — update these with your own Gmail App Password.

---

## 🎯 Quick Start (Copy-Paste)

```powershell
cd "d:\ROI-Based Intelligent Surveillance and Alert System\mpit"
.\myenv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest tests/ -v
python phy.py --dry-run
```

---

## ⚠️ Minor Observations (Not Bugs)

1. **Pygame audio warning**: On systems without audio hardware (e.g. headless/remote), pygame falls back to `winsound` — this is handled gracefully.
2. **User Manual references `system.py`**: The [User Manual.txt](file:///d:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/User%20Manual.txt) is outdated — it refers to `system.py` instead of `phy.py`. This is a documentation issue, not a code bug.
3. **Hardcoded frame count in ablation**: [`ablation.py` line 276](file:///d:/ROI-Based%20Intelligent%20Surveillance%20and%20Alert%20System/mpit/ablation.py#L276) returns a hardcoded `819` frame count for the test video — this works only for the included test video.
