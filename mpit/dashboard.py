"""
dashboard.py — Web dashboard for ROI Surveillance System.

A beautiful, dark-themed single-page dashboard that provides:
  - Real-time event feed with severity filtering
  - Statistics cards (total events, severity breakdown, tracks)
  - Interactive charts (severity pie, timeline, behaviour bar, dwell histogram)
  - Evidence gallery (photos)
  - System configuration overview
  - Hash chain verification status
  - Ablation comparison table

Usage:
    python dashboard.py                  # start on port 5000
    python dashboard.py --port 8080      # custom port
    python dashboard.py --import-log     # import JSONL → SQLite first
"""

import os
import sys
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

try:
    from flask import Flask, jsonify, send_from_directory, render_template_string
except ImportError:
    print("[Dashboard] Flask not installed. Installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    from flask import Flask, jsonify, send_from_directory, render_template_string

import config
from event_db import EventDB
from evidence import HashChain

app = Flask(__name__)
db = EventDB()


# ── Import evidence log on startup ────────────────────────────────────────

def auto_import():
    """Auto-import JSONL evidence log into SQLite if it exists."""
    if os.path.exists(config.EVIDENCE_LOG_PATH):
        count = db.import_from_jsonl()
        print(f"[Dashboard] Imported {count} events from evidence log.")
    else:
        print("[Dashboard] No evidence log found — database may be empty.")


# ── API Routes ────────────────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    """Get comprehensive statistics."""
    stats = db.get_full_stats()
    return jsonify(stats)


@app.route("/api/events")
def api_events():
    """Get paginated event list."""
    from flask import request
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    severity = request.args.get("severity")
    roi = request.args.get("roi")
    events = db.get_events(limit=limit, offset=offset,
                           severity=severity, roi_name=roi)
    return jsonify(events)


@app.route("/api/config")
def api_config():
    """Get current system configuration."""
    flags = {
        "USE_FOOT_POINT": config.USE_FOOT_POINT,
        "USE_CONF_THRESHOLD": config.USE_CONF_THRESHOLD,
        "CONF_THRESHOLD": config.CONF_THRESHOLD,
        "USE_TEMPORAL_CONFIRMATION": config.USE_TEMPORAL_CONFIRMATION,
        "TEMPORAL_N": config.TEMPORAL_N,
        "TEMPORAL_M": config.TEMPORAL_M,
        "USE_TRACKING": config.USE_TRACKING,
        "USE_POSE": config.USE_POSE,
        "BLUR_NON_INTRUDERS": config.BLUR_NON_INTRUDERS,
        "DETECT_EVERY_N_FRAMES": config.DETECT_EVERY_N_FRAMES,
        "INFERENCE_SIZE": config.INFERENCE_SIZE,
        "MAX_PHOTOS_PER_INCIDENT": config.MAX_PHOTOS_PER_INCIDENT,
        "LOW_TO_MEDIUM_SECONDS": config.LOW_TO_MEDIUM_SECONDS,
        "MEDIUM_TO_HIGH_SECONDS": config.MEDIUM_TO_HIGH_SECONDS,
        "HIGH_PERSON_COUNT": config.HIGH_PERSON_COUNT,
        "CLIP_PRE_SECONDS": config.CLIP_PRE_SECONDS,
        "CLIP_POST_SECONDS": config.CLIP_POST_SECONDS,
        "EMAIL_COOLDOWN_SECONDS": config.EMAIL_COOLDOWN_SECONDS,
    }
    return jsonify(flags)


@app.route("/api/chain/verify")
def api_chain_verify():
    """Verify the hash chain integrity."""
    valid, count, err = HashChain.verify()
    return jsonify({
        "valid": valid,
        "record_count": count,
        "error": err,
    })


@app.route("/api/ablation")
def api_ablation():
    """Get ablation comparison results."""
    runs = db.get_ablation_runs()
    return jsonify(runs)


@app.route("/api/photos")
def api_photos():
    """List evidence photos."""
    photos_dir = config.DETECTED_PHOTOS_DIR
    if not os.path.exists(photos_dir):
        return jsonify([])
    files = sorted(os.listdir(photos_dir), reverse=True)
    photos = [{"name": f, "path": f"/evidence-file/photos/{f}"} for f in files
              if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    return jsonify(photos[:50])  # limit to 50 most recent


@app.route("/evidence-file/photos/<path:filename>")
def serve_photo(filename):
    """Serve evidence photo files."""
    return send_from_directory(
        os.path.abspath(config.DETECTED_PHOTOS_DIR), filename
    )


# ── Dashboard HTML ────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ROI Surveillance Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --bg-primary: #0a0e1a;
            --bg-secondary: #111827;
            --bg-card: rgba(17, 24, 39, 0.8);
            --bg-glass: rgba(255, 255, 255, 0.03);
            --border-glass: rgba(255, 255, 255, 0.08);
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent-blue: #3b82f6;
            --accent-cyan: #06b6d4;
            --accent-purple: #8b5cf6;
            --accent-green: #10b981;
            --severity-low: #facc15;
            --severity-medium: #f97316;
            --severity-high: #ef4444;
            --success: #10b981;
            --danger: #ef4444;
            --glow-blue: 0 0 20px rgba(59, 130, 246, 0.15);
            --glow-purple: 0 0 20px rgba(139, 92, 246, 0.15);
            --radius: 16px;
            --radius-sm: 10px;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Inter', -apple-system, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* Animated background */
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background:
                radial-gradient(ellipse at 20% 50%, rgba(59, 130, 246, 0.06) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 20%, rgba(139, 92, 246, 0.06) 0%, transparent 50%),
                radial-gradient(ellipse at 50% 80%, rgba(6, 182, 212, 0.04) 0%, transparent 50%);
            pointer-events: none;
            z-index: 0;
        }

        .app { position: relative; z-index: 1; }

        /* Header */
        .header {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border-glass);
            padding: 16px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky; top: 0; z-index: 100;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 14px;
        }

        .logo {
            width: 40px; height: 40px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 20px;
            box-shadow: var(--glow-blue);
        }

        .header h1 {
            font-size: 1.2rem;
            font-weight: 600;
            background: linear-gradient(135deg, var(--text-primary), var(--accent-cyan));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .header-right {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 500;
        }

        .status-badge.verified {
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: var(--success);
        }

        .status-badge.broken {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: var(--danger);
        }

        .status-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }

        .status-dot.green { background: var(--success); }
        .status-dot.red { background: var(--danger); }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        /* Main layout */
        .main { padding: 24px 32px; max-width: 1600px; margin: 0 auto; }

        /* Tabs */
        .tabs {
            display: flex;
            gap: 4px;
            margin-bottom: 24px;
            background: var(--bg-card);
            padding: 4px;
            border-radius: var(--radius-sm);
            border: 1px solid var(--border-glass);
            width: fit-content;
        }

        .tab {
            padding: 8px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.85rem;
            font-weight: 500;
            color: var(--text-secondary);
            transition: all 0.2s;
            border: none;
            background: transparent;
        }

        .tab:hover { color: var(--text-primary); background: var(--bg-glass); }
        .tab.active {
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            color: white;
            box-shadow: var(--glow-blue);
        }

        .tab-content { display: none; }
        .tab-content.active { display: block; animation: fadeIn 0.3s; }

        @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

        /* Stat cards */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .stat-card {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border: 1px solid var(--border-glass);
            border-radius: var(--radius);
            padding: 20px;
            transition: all 0.3s;
        }

        .stat-card:hover {
            border-color: rgba(59, 130, 246, 0.3);
            box-shadow: var(--glow-blue);
            transform: translateY(-2px);
        }

        .stat-card .label {
            font-size: 0.78rem;
            font-weight: 500;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }

        .stat-card .value {
            font-size: 2rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--text-primary), var(--accent-cyan));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .stat-card .sub {
            font-size: 0.78rem;
            color: var(--text-muted);
            margin-top: 4px;
        }

        .stat-card.severity-high .value { background: linear-gradient(135deg, var(--severity-high), #f87171); -webkit-background-clip: text; }
        .stat-card.severity-medium .value { background: linear-gradient(135deg, var(--severity-medium), #fb923c); -webkit-background-clip: text; }
        .stat-card.severity-low .value { background: linear-gradient(135deg, var(--severity-low), #fde047); -webkit-background-clip: text; }

        /* Charts grid */
        .charts-grid {
            display: grid;
            grid-template-columns: 1fr 2fr;
            gap: 16px;
            margin-bottom: 24px;
        }

        .chart-card {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border: 1px solid var(--border-glass);
            border-radius: var(--radius);
            padding: 20px;
        }

        .chart-card h3 {
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-secondary);
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .chart-card canvas { max-height: 280px; }

        /* Event table */
        .event-table-wrapper {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border: 1px solid var(--border-glass);
            border-radius: var(--radius);
            overflow: hidden;
            margin-bottom: 24px;
        }

        .table-header {
            padding: 16px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border-glass);
        }

        .table-header h3 {
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-secondary);
        }

        .filter-group {
            display: flex;
            gap: 8px;
        }

        .filter-btn {
            padding: 4px 12px;
            border-radius: 6px;
            border: 1px solid var(--border-glass);
            background: transparent;
            color: var(--text-secondary);
            font-size: 0.75rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            font-family: 'Inter', sans-serif;
        }

        .filter-btn:hover, .filter-btn.active {
            border-color: var(--accent-blue);
            color: var(--accent-blue);
            background: rgba(59, 130, 246, 0.08);
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.82rem;
        }

        thead th {
            padding: 10px 16px;
            text-align: left;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            font-size: 0.7rem;
            letter-spacing: 0.5px;
            border-bottom: 1px solid var(--border-glass);
        }

        tbody td {
            padding: 10px 16px;
            border-bottom: 1px solid rgba(255,255,255,0.03);
            color: var(--text-secondary);
        }

        tbody tr { transition: background 0.15s; }
        tbody tr:hover { background: var(--bg-glass); }

        .severity-pill {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.72rem;
            font-weight: 600;
        }

        .severity-pill.HIGH { background: rgba(239,68,68,0.15); color: #f87171; }
        .severity-pill.MEDIUM { background: rgba(249,115,22,0.15); color: #fb923c; }
        .severity-pill.LOW { background: rgba(250,204,21,0.15); color: #fde047; }

        /* Config panel */
        .config-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 16px;
        }

        .config-section {
            background: var(--bg-card);
            border: 1px solid var(--border-glass);
            border-radius: var(--radius);
            padding: 20px;
        }

        .config-section h3 {
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-secondary);
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border-glass);
        }

        .config-row {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            font-size: 0.82rem;
        }

        .config-key { color: var(--text-muted); font-family: 'Consolas', monospace; font-size: 0.78rem; }
        .config-val { font-weight: 600; }
        .config-val.on { color: var(--success); }
        .config-val.off { color: var(--text-muted); }

        /* Ablation table */
        .ablation-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.82rem;
        }

        .ablation-table th {
            padding: 10px 14px;
            text-align: left;
            font-weight: 600;
            color: var(--text-muted);
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid var(--border-glass);
        }

        .ablation-table td {
            padding: 10px 14px;
            border-bottom: 1px solid rgba(255,255,255,0.03);
            color: var(--text-secondary);
        }

        .ablation-table tr:hover { background: var(--bg-glass); }

        .best-value { color: var(--success); font-weight: 600; }

        /* Photo gallery */
        .gallery {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 12px;
        }

        .gallery-item {
            background: var(--bg-card);
            border: 1px solid var(--border-glass);
            border-radius: var(--radius-sm);
            overflow: hidden;
            transition: all 0.3s;
            cursor: pointer;
        }

        .gallery-item:hover {
            border-color: var(--accent-blue);
            box-shadow: var(--glow-blue);
            transform: translateY(-2px);
        }

        .gallery-item img {
            width: 100%;
            aspect-ratio: 16/9;
            object-fit: cover;
        }

        .gallery-item .caption {
            padding: 8px 12px;
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        /* Loading */
        .loading {
            text-align: center;
            padding: 40px;
            color: var(--text-muted);
        }

        .spinner {
            width: 32px; height: 32px;
            border: 3px solid var(--border-glass);
            border-top-color: var(--accent-blue);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin: 0 auto 12px;
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        /* Empty state */
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-muted);
        }

        .empty-state .icon { font-size: 3rem; margin-bottom: 12px; opacity: 0.5; }

        /* Responsive */
        @media (max-width: 768px) {
            .header { padding: 12px 16px; }
            .main { padding: 16px; }
            .charts-grid { grid-template-columns: 1fr; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="app">
        <!-- Header -->
        <header class="header">
            <div class="header-left">
                <div class="logo">🛡️</div>
                <h1>ROI Surveillance Dashboard</h1>
            </div>
            <div class="header-right">
                <div class="status-badge" id="chain-status">
                    <span class="status-dot"></span>
                    <span>Loading...</span>
                </div>
            </div>
        </header>

        <main class="main">
            <!-- Tabs -->
            <div class="tabs">
                <button class="tab active" data-tab="overview">Overview</button>
                <button class="tab" data-tab="events">Events</button>
                <button class="tab" data-tab="evidence">Evidence</button>
                <button class="tab" data-tab="config">Config</button>
                <button class="tab" data-tab="ablation">Ablation</button>
            </div>

            <!-- Overview Tab -->
            <div class="tab-content active" id="tab-overview">
                <div class="stats-grid" id="stats-cards">
                    <div class="loading"><div class="spinner"></div>Loading statistics...</div>
                </div>
                <div class="charts-grid">
                    <div class="chart-card">
                        <h3>📊 Severity Distribution</h3>
                        <canvas id="chart-severity"></canvas>
                    </div>
                    <div class="chart-card">
                        <h3>📈 Event Timeline</h3>
                        <canvas id="chart-timeline"></canvas>
                    </div>
                </div>
                <div class="charts-grid">
                    <div class="chart-card">
                        <h3>🏃 Behaviour Distribution</h3>
                        <canvas id="chart-behaviour"></canvas>
                    </div>
                    <div class="chart-card">
                        <h3>⏱️ Dwell Time Distribution</h3>
                        <canvas id="chart-dwell"></canvas>
                    </div>
                </div>
            </div>

            <!-- Events Tab -->
            <div class="tab-content" id="tab-events">
                <div class="event-table-wrapper">
                    <div class="table-header">
                        <h3>📋 Event Log</h3>
                        <div class="filter-group">
                            <button class="filter-btn active" data-severity="all">All</button>
                            <button class="filter-btn" data-severity="HIGH">HIGH</button>
                            <button class="filter-btn" data-severity="MEDIUM">MEDIUM</button>
                            <button class="filter-btn" data-severity="LOW">LOW</button>
                        </div>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Track</th>
                                <th>Severity</th>
                                <th>ROI</th>
                                <th>Dwell</th>
                                <th>Behaviour</th>
                                <th>Reasons</th>
                            </tr>
                        </thead>
                        <tbody id="events-tbody">
                            <tr><td colspan="7" class="loading"><div class="spinner"></div>Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Evidence Tab -->
            <div class="tab-content" id="tab-evidence">
                <div class="chart-card" style="margin-bottom: 24px;">
                    <h3>📸 Evidence Gallery</h3>
                    <div class="gallery" id="gallery"></div>
                </div>
            </div>

            <!-- Config Tab -->
            <div class="tab-content" id="tab-config">
                <div class="config-grid" id="config-grid">
                    <div class="loading"><div class="spinner"></div>Loading configuration...</div>
                </div>
            </div>

            <!-- Ablation Tab -->
            <div class="tab-content" id="tab-ablation">
                <div class="chart-card" style="margin-bottom:24px">
                    <h3>🔬 Ablation Comparison</h3>
                    <div id="ablation-content">
                        <div class="loading"><div class="spinner"></div>Loading ablation results...</div>
                    </div>
                </div>
                <div class="charts-grid">
                    <div class="chart-card">
                        <h3>⚡ FPS Comparison</h3>
                        <canvas id="chart-ablation-fps"></canvas>
                    </div>
                    <div class="chart-card">
                        <h3>📊 Event Count Comparison</h3>
                        <canvas id="chart-ablation-events"></canvas>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <script>
    // ── State ──────────────────────────────────────────────────────────────
    let charts = {};
    let currentFilter = 'all';

    // ── Tab switching ─────────────────────────────────────────────────────
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById('tab-' + tab.dataset.tab).classList.add('active');

            if (tab.dataset.tab === 'events') loadEvents();
            if (tab.dataset.tab === 'evidence') loadPhotos();
            if (tab.dataset.tab === 'config') loadConfig();
            if (tab.dataset.tab === 'ablation') loadAblation();
        });
    });

    // ── Filter buttons ────────────────────────────────────────────────────
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.dataset.severity;
            loadEvents();
        });
    });

    // ── API helpers ───────────────────────────────────────────────────────
    async function api(path) {
        const res = await fetch(path);
        return await res.json();
    }

    // ── Load stats and charts ─────────────────────────────────────────────
    async function loadOverview() {
        try {
            const stats = await api('/api/stats');
            renderStats(stats);
            renderSeverityChart(stats.severity_counts);
            renderTimelineChart(stats.timeline);
            renderBehaviourChart(stats.behaviour_counts);
            renderDwellChart(stats.timeline);
        } catch (e) {
            console.error('Error loading stats:', e);
        }
    }

    function renderStats(stats) {
        const sev = stats.severity_counts || {};
        const dwell = stats.dwell_stats || {};
        document.getElementById('stats-cards').innerHTML = `
            <div class="stat-card">
                <div class="label">Total Events</div>
                <div class="value">${(stats.total_events || 0).toLocaleString()}</div>
                <div class="sub">${stats.unique_tracks || 0} unique tracks</div>
            </div>
            <div class="stat-card severity-high">
                <div class="label">High Severity</div>
                <div class="value">${(sev.HIGH || 0).toLocaleString()}</div>
                <div class="sub">Critical intrusions</div>
            </div>
            <div class="stat-card severity-medium">
                <div class="label">Medium Severity</div>
                <div class="value">${(sev.MEDIUM || 0).toLocaleString()}</div>
                <div class="sub">Elevated alerts</div>
            </div>
            <div class="stat-card severity-low">
                <div class="label">Low Severity</div>
                <div class="value">${(sev.LOW || 0).toLocaleString()}</div>
                <div class="sub">Initial detections</div>
            </div>
            <div class="stat-card">
                <div class="label">Avg Dwell</div>
                <div class="value">${(dwell.avg || 0).toFixed(1)}s</div>
                <div class="sub">Max: ${(dwell.max || 0).toFixed(1)}s</div>
            </div>
        `;
    }

    function renderSeverityChart(sev) {
        const ctx = document.getElementById('chart-severity');
        if (charts.severity) charts.severity.destroy();
        charts.severity = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['HIGH', 'MEDIUM', 'LOW'],
                datasets: [{
                    data: [sev.HIGH || 0, sev.MEDIUM || 0, sev.LOW || 0],
                    backgroundColor: ['#ef4444', '#f97316', '#facc15'],
                    borderWidth: 0,
                    hoverOffset: 8,
                }]
            },
            options: {
                responsive: true,
                cutout: '65%',
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#94a3b8', padding: 16, font: { family: 'Inter' } } }
                }
            }
        });
    }

    function renderTimelineChart(timeline) {
        const ctx = document.getElementById('chart-timeline');
        if (charts.timeline) charts.timeline.destroy();
        if (!timeline || timeline.length === 0) return;

        const labels = timeline.map(t => t.time_bucket ? t.time_bucket.split('T').pop() || t.time_bucket : '');
        // Show at most 30 data points
        const step = Math.max(1, Math.floor(labels.length / 30));
        const filtered = timeline.filter((_, i) => i % step === 0);

        charts.timeline = new Chart(ctx, {
            type: 'line',
            data: {
                labels: filtered.map(t => t.time_bucket ? t.time_bucket.split('T').pop() || t.time_bucket : ''),
                datasets: [
                    { label: 'HIGH', data: filtered.map(t => t.high || 0), borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.1)', fill: true, tension: 0.3, pointRadius: 1 },
                    { label: 'MEDIUM', data: filtered.map(t => t.medium || 0), borderColor: '#f97316', backgroundColor: 'rgba(249,115,22,0.1)', fill: true, tension: 0.3, pointRadius: 1 },
                    { label: 'LOW', data: filtered.map(t => t.low || 0), borderColor: '#facc15', backgroundColor: 'rgba(250,204,21,0.1)', fill: true, tension: 0.3, pointRadius: 1 },
                ]
            },
            options: {
                responsive: true,
                interaction: { intersect: false, mode: 'index' },
                scales: {
                    x: { ticks: { color: '#64748b', maxTicksLimit: 10, font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.03)' } },
                    y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.03)' }, beginAtZero: true }
                },
                plugins: { legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } } }
            }
        });
    }

    function renderBehaviourChart(behaviours) {
        const ctx = document.getElementById('chart-behaviour');
        if (charts.behaviour) charts.behaviour.destroy();
        if (!behaviours || Object.keys(behaviours).length === 0) {
            ctx.parentElement.innerHTML += '<div class="empty-state"><div class="icon">🏃</div><p>No behaviour data</p></div>';
            return;
        }

        const labels = Object.keys(behaviours);
        const values = Object.values(behaviours);
        const colors = ['#3b82f6', '#06b6d4', '#8b5cf6', '#10b981', '#f97316'];

        charts.behaviour = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: labels.map((_, i) => colors[i % colors.length] + '80'),
                    borderColor: labels.map((_, i) => colors[i % colors.length]),
                    borderWidth: 1,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                indexAxis: 'y',
                scales: {
                    x: { ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.03)' }, beginAtZero: true },
                    y: { ticks: { color: '#94a3b8' }, grid: { display: false } }
                },
                plugins: { legend: { display: false } }
            }
        });
    }

    function renderDwellChart(timeline) {
        const ctx = document.getElementById('chart-dwell');
        if (charts.dwell) charts.dwell.destroy();
        // Create a simple bar chart showing event density
        if (!timeline || timeline.length === 0) return;

        const step = Math.max(1, Math.floor(timeline.length / 20));
        const filtered = timeline.filter((_, i) => i % step === 0);

        charts.dwell = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: filtered.map(t => t.time_bucket ? t.time_bucket.split('T').pop() || '' : ''),
                datasets: [{
                    label: 'Events',
                    data: filtered.map(t => t.cnt || 0),
                    backgroundColor: 'rgba(59, 130, 246, 0.4)',
                    borderColor: '#3b82f6',
                    borderWidth: 1,
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                scales: {
                    x: { ticks: { color: '#64748b', maxTicksLimit: 10, font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.03)' } },
                    y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.03)' }, beginAtZero: true }
                },
                plugins: { legend: { display: false } }
            }
        });
    }

    // ── Events table ──────────────────────────────────────────────────────
    async function loadEvents() {
        const params = currentFilter !== 'all' ? `?severity=${currentFilter}&limit=100` : '?limit=100';
        try {
            const events = await api('/api/events' + params);
            const tbody = document.getElementById('events-tbody');
            if (events.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="empty-state"><div class="icon">📋</div><p>No events found</p></td></tr>';
                return;
            }
            tbody.innerHTML = events.map(e => {
                let reasons = '';
                try { reasons = JSON.parse(e.reasons || '[]').join(', '); } catch { reasons = e.reasons || ''; }
                const time = e.timestamp ? e.timestamp.split('T')[1]?.substring(0, 8) || e.timestamp : '';
                return `<tr>
                    <td>${time}</td>
                    <td>${e.incident_id || '-'}</td>
                    <td><span class="severity-pill ${e.severity}">${e.severity}</span></td>
                    <td>${e.roi_name || '-'}</td>
                    <td>${(e.dwell_seconds || 0).toFixed(1)}s</td>
                    <td>${e.behaviour || '-'}</td>
                    <td style="color:var(--text-muted);font-size:0.75rem">${reasons}</td>
                </tr>`;
            }).join('');
        } catch (e) {
            console.error('Error loading events:', e);
        }
    }

    // ── Evidence gallery ──────────────────────────────────────────────────
    async function loadPhotos() {
        try {
            const photos = await api('/api/photos');
            const gallery = document.getElementById('gallery');
            if (photos.length === 0) {
                gallery.innerHTML = '<div class="empty-state"><div class="icon">📸</div><p>No evidence photos</p></div>';
                return;
            }
            gallery.innerHTML = photos.map(p => `
                <div class="gallery-item" onclick="window.open('${p.path}','_blank')">
                    <img src="${p.path}" alt="${p.name}" loading="lazy">
                    <div class="caption">${p.name}</div>
                </div>
            `).join('');
        } catch (e) {
            console.error('Error loading photos:', e);
        }
    }

    // ── Config panel ──────────────────────────────────────────────────────
    async function loadConfig() {
        try {
            const cfg = await api('/api/config');
            const grid = document.getElementById('config-grid');

            const flagKeys = ['USE_FOOT_POINT', 'USE_CONF_THRESHOLD', 'USE_TEMPORAL_CONFIRMATION',
                            'USE_TRACKING', 'USE_POSE', 'BLUR_NON_INTRUDERS'];
            const threshKeys = ['CONF_THRESHOLD', 'TEMPORAL_N', 'TEMPORAL_M',
                              'LOW_TO_MEDIUM_SECONDS', 'MEDIUM_TO_HIGH_SECONDS', 'HIGH_PERSON_COUNT'];
            const perfKeys = ['DETECT_EVERY_N_FRAMES', 'INFERENCE_SIZE', 'MAX_PHOTOS_PER_INCIDENT',
                            'CLIP_PRE_SECONDS', 'CLIP_POST_SECONDS', 'EMAIL_COOLDOWN_SECONDS'];

            function renderSection(title, keys) {
                return `<div class="config-section"><h3>${title}</h3>${
                    keys.map(k => {
                        const v = cfg[k];
                        const isFlag = typeof v === 'boolean';
                        return `<div class="config-row">
                            <span class="config-key">${k}</span>
                            <span class="config-val ${isFlag ? (v ? 'on' : 'off') : ''}">${
                                isFlag ? (v ? '✓ ON' : '✗ OFF') : v
                            }</span>
                        </div>`;
                    }).join('')
                }</div>`;
            }

            grid.innerHTML = renderSection('⚡ Feature Flags', flagKeys)
                           + renderSection('📏 Thresholds', threshKeys)
                           + renderSection('⚙️ Performance', perfKeys);
        } catch (e) {
            console.error('Error loading config:', e);
        }
    }

    // ── Ablation results ──────────────────────────────────────────────────
    async function loadAblation() {
        try {
            const runs = await api('/api/ablation');
            const content = document.getElementById('ablation-content');

            if (runs.length === 0) {
                content.innerHTML = `<div class="empty-state">
                    <div class="icon">🔬</div>
                    <p>No ablation results yet</p>
                    <p style="font-size:0.8rem;margin-top:8px;color:var(--text-muted)">
                        Run: <code>python ablation.py</code> to generate results
                    </p>
                </div>`;
                return;
            }

            // Find best values for highlighting
            const bestFps = Math.max(...runs.map(r => r.avg_fps || 0));
            const fewestEvents = Math.min(...runs.map(r => r.confirmed_intrusions || 0));

            content.innerHTML = `<table class="ablation-table">
                <thead><tr>
                    <th>Profile</th><th>FPS</th><th>Events</th>
                    <th>LOW</th><th>MED</th><th>HIGH</th>
                    <th>Tracks</th><th>Avg Dwell</th><th>Max Dwell</th>
                    <th>Time</th><th>Description</th>
                </tr></thead>
                <tbody>${runs.map(r => `<tr>
                    <td style="font-weight:600">${r.run_label}</td>
                    <td class="${r.avg_fps >= bestFps ? 'best-value' : ''}">${(r.avg_fps||0).toFixed(1)}</td>
                    <td class="${r.confirmed_intrusions <= fewestEvents ? 'best-value' : ''}">${r.confirmed_intrusions||0}</td>
                    <td>${r.low_count||0}</td>
                    <td>${r.medium_count||0}</td>
                    <td>${r.high_count||0}</td>
                    <td>${r.unique_tracks||0}</td>
                    <td>${(r.avg_dwell||0).toFixed(1)}s</td>
                    <td>${(r.max_dwell||0).toFixed(1)}s</td>
                    <td>${(r.wall_seconds||0).toFixed(1)}s</td>
                    <td style="color:var(--text-muted);font-size:0.75rem">${r.notes||''}</td>
                </tr>`).join('')}</tbody>
            </table>`;

            // Ablation charts
            renderAblationCharts(runs);
        } catch (e) {
            console.error('Error loading ablation:', e);
        }
    }

    function renderAblationCharts(runs) {
        const labels = runs.map(r => r.run_label);

        // FPS chart
        const fpsCtx = document.getElementById('chart-ablation-fps');
        if (charts.ablationFps) charts.ablationFps.destroy();
        charts.ablationFps = new Chart(fpsCtx, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'FPS',
                    data: runs.map(r => r.avg_fps || 0),
                    backgroundColor: labels.map((_, i) => `hsla(${220 + i * 25}, 70%, 55%, 0.6)`),
                    borderColor: labels.map((_, i) => `hsl(${220 + i * 25}, 70%, 55%)`),
                    borderWidth: 1,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                scales: {
                    x: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { display: false } },
                    y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.03)' }, beginAtZero: true }
                },
                plugins: { legend: { display: false } }
            }
        });

        // Events chart (stacked)
        const evtCtx = document.getElementById('chart-ablation-events');
        if (charts.ablationEvents) charts.ablationEvents.destroy();
        charts.ablationEvents = new Chart(evtCtx, {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    { label: 'HIGH', data: runs.map(r => r.high_count || 0), backgroundColor: 'rgba(239,68,68,0.7)', borderRadius: 4 },
                    { label: 'MEDIUM', data: runs.map(r => r.medium_count || 0), backgroundColor: 'rgba(249,115,22,0.7)', borderRadius: 4 },
                    { label: 'LOW', data: runs.map(r => r.low_count || 0), backgroundColor: 'rgba(250,204,21,0.7)', borderRadius: 4 },
                ]
            },
            options: {
                responsive: true,
                scales: {
                    x: { stacked: true, ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { display: false } },
                    y: { stacked: true, ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.03)' }, beginAtZero: true }
                },
                plugins: { legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } } }
            }
        });
    }

    // ── Chain verification ─────────────────────────────────────────────────
    async function checkChain() {
        try {
            const result = await api('/api/chain/verify');
            const badge = document.getElementById('chain-status');
            if (result.valid) {
                badge.className = 'status-badge verified';
                badge.innerHTML = `<span class="status-dot green"></span>Chain Verified · ${result.record_count} records`;
            } else {
                badge.className = 'status-badge broken';
                badge.innerHTML = `<span class="status-dot red"></span>Chain Broken`;
            }
        } catch (e) {
            const badge = document.getElementById('chain-status');
            badge.className = 'status-badge';
            badge.innerHTML = `<span class="status-dot"></span>Offline`;
        }
    }

    // ── Initialize ────────────────────────────────────────────────────────
    loadOverview();
    checkChain();
    </script>
</body>
</html>"""


@app.route("/")
def index():
    """Serve the dashboard."""
    return render_template_string(DASHBOARD_HTML)


# ── Entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ROI Surveillance Dashboard")
    parser.add_argument("--port", type=int, default=5000, help="Port (default 5000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host")
    parser.add_argument("--import-log", action="store_true",
                        help="Import JSONL evidence log into database first")
    args = parser.parse_args()

    auto_import()

    print(f"\n+{'='*52}+")
    print(f"|  ROI Surveillance Dashboard                        |")
    print(f"|  http://{args.host}:{args.port}                       |")
    print(f"+{'='*52}+\n")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
