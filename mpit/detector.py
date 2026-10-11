"""
detector.py — YOLOv5 model loading, inference, and class/confidence filtering.

Handles:
  - Loading YOLOv5s via torch.hub (with local weight fallback for offline use)
  - Inference with configurable input size
  - Optional cropping to ROI bounding rect before inference
  - Class filtering (only TARGET_CLASSES)
  - Confidence threshold filtering
"""

import os
import torch
import cv2
import numpy as np

import config


class Detector:
    """Wraps YOLOv5 model loading and inference."""

    def __init__(self):
        self.model = None
        self._load_model()

    def _load_model(self):
        """
        Load YOLOv5s model.  Tries torch.hub first (downloads if needed),
        then falls back to local yolov5s.pt for offline use.
        """
        local_weights = os.path.join(os.path.dirname(__file__), "yolov5s.pt")

        try:
            # Try loading from hub (will use cache if available)
            self.model = torch.hub.load(
                'ultralytics/yolov5', 'yolov5s', pretrained=True, verbose=False
            )
            print("[Detector] YOLOv5s loaded from torch hub.")
        except Exception as e:
            print(f"[Detector] Hub load failed ({e}), trying local weights...")
            if os.path.exists(local_weights):
                try:
                    self.model = torch.hub.load(
                        'ultralytics/yolov5', 'custom', path=local_weights, verbose=False
                    )
                    print("[Detector] YOLOv5s loaded from local weights.")
                except Exception as e2:
                    print(f"[Detector] Local load also failed: {e2}")
                    raise RuntimeError("Cannot load YOLOv5 model.") from e2
            else:
                raise RuntimeError(
                    f"Cannot load YOLOv5 model and local weights not found at {local_weights}"
                ) from e

        # Configure model
        self.model.conf = config.CONF_THRESHOLD if config.USE_CONF_THRESHOLD else 0.25
        self.model.classes = None  # we filter manually for flexibility

    def detect(self, frame, roi_bounds=None):
        """
        Run YOLO inference on a frame.

        Args:
            frame: BGR image (numpy array)
            roi_bounds: optional (x, y, w, h) tuple to crop before inference

        Returns:
            List of detection dicts: {name, x1, y1, x2, y2, confidence}
            Coordinates are in the ORIGINAL frame coordinate system.
        """
        crop_offset_x = 0
        crop_offset_y = 0
        inference_frame = frame

        # Optional: crop to ROI bounding rectangle
        if config.CROP_TO_ROI_BOUNDS and roi_bounds is not None:
            rx, ry, rw, rh = roi_bounds
            fh, fw = frame.shape[:2]
            # Clamp to frame bounds
            rx = max(0, rx)
            ry = max(0, ry)
            rw = min(rw, fw - rx)
            rh = min(rh, fh - ry)
            if rw > 50 and rh > 50:  # only crop if reasonably large
                inference_frame = frame[ry:ry+rh, rx:rx+rw]
                crop_offset_x = rx
                crop_offset_y = ry

        # Resize for inference
        height, width = inference_frame.shape[:2]
        ratio = height / width
        target_w = config.INFERENCE_SIZE
        target_h = int(target_w * ratio)
        resized = cv2.resize(inference_frame, (target_w, target_h))

        # Scale factors to map back to the inference_frame coordinates
        scale_x = width / target_w
        scale_y = height / target_h

        # Run inference
        results = self.model(resized)

        detections = []
        for _, row in results.pandas().xyxy[0].iterrows():
            name = str(row['name'])
            confidence = float(row['confidence'])

            # Class filter: only keep target classes
            if name not in config.TARGET_CLASSES:
                continue

            # Confidence filter
            if config.USE_CONF_THRESHOLD and confidence < config.CONF_THRESHOLD:
                continue

            # Map coordinates back to original frame
            x1 = int(row['xmin'] * scale_x) + crop_offset_x
            y1 = int(row['ymin'] * scale_y) + crop_offset_y
            x2 = int(row['xmax'] * scale_x) + crop_offset_x
            y2 = int(row['ymax'] * scale_y) + crop_offset_y

            detections.append({
                'name': name,
                'x1': x1, 'y1': y1,
                'x2': x2, 'y2': y2,
                'confidence': confidence,
            })

        return detections
