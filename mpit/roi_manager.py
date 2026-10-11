"""
roi_manager.py — ROI drawing, save/load rois.json, point-in-polygon testing.

Supports multiple named ROIs, each with:
  - name: human-readable name (e.g. "Zone A")
  - points: list of [x, y] polygon vertices
  - restricted_hours: optional [start_h:start_m, end_h:end_m] string pair
  - sensitivity: weight multiplier for severity scoring (default 1.0)

Keyboard controls during drawing:
  Left-click  : add a vertex
  Right-click : clear current polygon
  S           : save current ROI (must have ≥ 4 points)
  N           : start drawing a new ROI (after saving current one)
  Q           : quit drawing mode and proceed
"""

import json
import os
import cv2
import numpy as np

import config


class ROIManager:
    """Manages interactive ROI drawing, persistence, and point-in-polygon tests."""

    def __init__(self, json_path=None):
        self.json_path = json_path or config.ROI_JSON_PATH
        self.rois = []           # list of dicts: {name, points, restricted_hours, sensitivity}
        self._drawing_pts = []   # temp points for the current drawing session
        self._drawing_name = ""  # name assigned during drawing

    # ── Persistence ────────────────────────────────────────────────────────

    def load(self):
        """Load ROIs from JSON file.  Returns True if loaded successfully."""
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    self.rois = data
                    print(f"[ROI] Loaded {len(self.rois)} ROI(s) from {self.json_path}")
                    return True
            except (json.JSONDecodeError, IOError) as e:
                print(f"[ROI] Failed to load {self.json_path}: {e}")
        return False

    def save(self):
        """Persist current ROIs to JSON file."""
        try:
            with open(self.json_path, "w") as f:
                json.dump(self.rois, f, indent=2)
            print(f"[ROI] Saved {len(self.rois)} ROI(s) to {self.json_path}")
        except IOError as e:
            print(f"[ROI] Failed to save: {e}")

    # ── Drawing ────────────────────────────────────────────────────────────

    def _mouse_callback(self, event, x, y, flags, param):
        """OpenCV mouse callback for interactive ROI drawing."""
        if event == cv2.EVENT_LBUTTONDOWN:
            self._drawing_pts.append([x, y])
            print(f"[ROI] Point added: ({x}, {y})  — total: {len(self._drawing_pts)}")
        elif event == cv2.EVENT_RBUTTONDOWN:
            self._drawing_pts.clear()
            print("[ROI] Points cleared.")

    def draw_interactive(self, frame):
        """
        Let the user draw ROIs interactively on the given frame.

        Controls:
          Left-click  : add vertex
          Right-click : clear polygon
          S           : save current ROI (≥ 4 points required)
          N           : start a new ROI
          Q           : finish and proceed

        Returns the list of ROI dicts.
        """
        window_name = "Draw ROI"
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, self._mouse_callback)
        roi_index = len(self.rois) + 1

        print("\n══════════════════════════════════════════")
        print("  ROI Drawing Mode")
        print("  Left-click : add vertex")
        print("  Right-click: clear polygon")
        print("  S          : save current ROI (need ≥ 4 pts)")
        print("  N          : start drawing another ROI")
        print("  Q          : quit drawing, proceed")
        print("══════════════════════════════════════════\n")

        while True:
            display = frame.copy()

            # Draw already-saved ROIs in green
            for roi in self.rois:
                pts_np = np.array(roi["points"], dtype=np.int32)
                cv2.polylines(display, [pts_np], True, (0, 255, 0), 2)
                # Label
                if len(roi["points"]) > 0:
                    cv2.putText(display, roi["name"], tuple(roi["points"][0]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Draw current in-progress polygon in yellow
            if len(self._drawing_pts) > 0:
                pts_np = np.array(self._drawing_pts, dtype=np.int32)
                cv2.polylines(display, [pts_np], False, (0, 255, 255), 2)
                for pt in self._drawing_pts:
                    cv2.circle(display, tuple(pt), 4, (0, 255, 255), -1)

            # Instructions overlay
            cv2.putText(display, "S=save  N=new  Q=quit  LClick=add  RClick=clear",
                        (10, display.shape[0] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            cv2.imshow(window_name, display)
            key = cv2.waitKey(30) & 0xFF

            if key == ord('s') or key == ord('S'):
                if len(self._drawing_pts) >= 4:
                    roi_name = f"Zone {roi_index}"
                    self.rois.append({
                        "name": roi_name,
                        "points": list(self._drawing_pts),
                        "restricted_hours": None,
                        "sensitivity": 1.0,
                    })
                    print(f"[ROI] Saved '{roi_name}' with {len(self._drawing_pts)} points.")
                    self._drawing_pts = []
                    roi_index += 1
                else:
                    print("[ROI] Need at least 4 points to save a ROI.")

            elif key == ord('n') or key == ord('N'):
                if len(self._drawing_pts) >= 4:
                    # Auto-save current before starting new
                    roi_name = f"Zone {roi_index}"
                    self.rois.append({
                        "name": roi_name,
                        "points": list(self._drawing_pts),
                        "restricted_hours": None,
                        "sensitivity": 1.0,
                    })
                    print(f"[ROI] Auto-saved '{roi_name}'. Starting new ROI.")
                    roi_index += 1
                self._drawing_pts = []
                print("[ROI] Drawing new ROI...")

            elif key == ord('q') or key == ord('Q'):
                # Auto-save if there are unsaved points
                if len(self._drawing_pts) >= 4:
                    roi_name = f"Zone {roi_index}"
                    self.rois.append({
                        "name": roi_name,
                        "points": list(self._drawing_pts),
                        "restricted_hours": None,
                        "sensitivity": 1.0,
                    })
                    print(f"[ROI] Auto-saved '{roi_name}' on quit.")
                break

        cv2.destroyWindow(window_name)

        if len(self.rois) > 0:
            self.save()
        else:
            print("[ROI] Warning: no ROIs defined.")

        return self.rois

    # ── Point-in-polygon test ──────────────────────────────────────────────

    @staticmethod
    def point_in_polygon(point, polygon_pts):
        """
        Check if a point (x, y) is inside a polygon.

        Args:
            point: tuple (x, y)
            polygon_pts: list of [x, y] or np.array of shape (N, 2)

        Returns:
            True if inside or on the boundary, False otherwise.
        """
        poly = np.array(polygon_pts, dtype=np.int32)
        result = cv2.pointPolygonTest(poly, (int(point[0]), int(point[1])), False)
        return result >= 0  # >= 0 means inside or on boundary

    @staticmethod
    def get_foot_point(x1, y1, x2, y2):
        """Return bottom-center of a bounding box: ((x1+x2)/2, y2)."""
        return (int((x1 + x2) / 2), int(y2))

    @staticmethod
    def get_center_point(x1, y1, x2, y2):
        """Return center of a bounding box: ((x1+x2)/2, (y1+y2)/2)."""
        return (int((x1 + x2) / 2), int((y1 + y2) / 2))

    # ── ROI bounding rectangle (for CROP_TO_ROI_BOUNDS) ───────────────────

    def get_combined_bounding_rect(self, margin=50):
        """
        Get the bounding rectangle that encloses all ROI polygons,
        with an optional margin.  Returns (x, y, w, h) or None.
        """
        if not self.rois:
            return None

        all_pts = []
        for roi in self.rois:
            all_pts.extend(roi["points"])

        if not all_pts:
            return None

        pts_np = np.array(all_pts, dtype=np.int32)
        x, y, w, h = cv2.boundingRect(pts_np)
        # Add margin
        x = max(0, x - margin)
        y = max(0, y - margin)
        w += 2 * margin
        h += 2 * margin
        return (x, y, w, h)

    # ── Drawing ROIs on frame ─────────────────────────────────────────────

    def draw_rois_on_frame(self, frame, alpha=0.1):
        """Draw all ROIs as semi-transparent green overlays on the frame."""
        for roi in self.rois:
            pts = np.array(roi["points"], dtype=np.int32)
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], (0, 255, 0))
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
            cv2.polylines(frame, [pts], True, (0, 255, 0), 2)
            # Draw ROI name
            if len(roi["points"]) > 0:
                cv2.putText(frame, roi["name"], tuple(roi["points"][0]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        return frame

    # ── Legacy compatibility ──────────────────────────────────────────────

    def get_single_roi_pts(self):
        """
        Return the points of the first ROI as a numpy array,
        for backward compatibility with the original single-ROI code.
        Returns None if no ROIs are defined.
        """
        if self.rois and len(self.rois) > 0:
            return np.array(self.rois[0]["points"], dtype=np.int32)
        return None
