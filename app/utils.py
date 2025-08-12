import cv2
import os
import numpy as np
from collections import defaultdict
from ultralytics import YOLO
import torch


def _compute_iou(box_a, box_b):
    """Compute IoU between two boxes in (x1, y1, x2, y2) format."""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter_area
    return (inter_area / union) if union > 0 else 0.0


def process_video(input_path, output_path, *, conf_global: float = 0.6, motorcycle_conf: float = 0.75, iou_thresh: float = 0.3):
    """Processes a video with YOLOv8 vehicle detection and returns summary stats."""
    try:
        # Initialize YOLOv8 model
        model = YOLO('yolov8n.pt')  # Load the pretrained model
        
        # Define class mapping for vehicles
        class_map = {
            2: 'car',      # car
            3: 'motorcycle',  # motorcycle
            5: 'bus',      # bus
            7: 'truck'     # truck
        }

        # Open the video file
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise IOError("Cannot open video file")

        # Get video properties
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_area = width * height

        # Ensure the output path ends with .mp4
        if not output_path.endswith('.mp4'):
            output_path = output_path.rsplit('.', 1)[0] + '.mp4'

        # Create output directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Use H.264 codec with .mp4 container for web compatibility
        if os.name == 'nt':  # Windows
            fourcc = cv2.VideoWriter_fourcc(*'H264')
        else:  # Linux/Mac
            fourcc = cv2.VideoWriter_fourcc(*'avc1')

        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        if not out.isOpened():
            raise IOError("Cannot create output video file")

        # Define lane regions
        lane_heights = [int(height * y) for y in [0.33, 0.66]]
        
        # Vehicle detection settings
        vehicle_colors = {
            'car': (66, 135, 245),      # Blue
            'truck': (245, 66, 66),      # Red
            'bus': (66, 245, 78),        # Green
            'motorcycle': (245, 193, 66)  # Orange
        }

        # Initialize lane statistics display container
        lane_stats = {
            'Left Lane': defaultdict(int),
            'Middle Lane': defaultdict(int),
            'Right Lane': defaultdict(int)
        }

        # Tracking structures for unique counts per class
        tracks = {name: [] for name in vehicle_colors.keys()}
        next_track_id = {name: 1 for name in vehicle_colors.keys()}
        unique_counts = {name: 0 for name in vehicle_colors.keys()}

        # Density estimate via max concurrent detections
        max_total_concurrent = 0
        # Sampled density timeline (percentages)
        density_series: list[float] = []
        sample_every = max(1, fps // 5)  # ~5 samples per second
        # Track average confidence of accepted detections
        accepted_conf_sum = 0.0
        accepted_conf_count = 0

        # Maximum vehicles per lane for density calculation
        MAX_VEHICLES_PER_LANE = 15
        NUM_LANES = 3
        frame_count = 0
        frame_idx = 0
        TRACK_TIMEOUT = 30  # frames without update before deletion
        IOU_THRESHOLD = iou_thresh
        CONFIRM_HITS = 3    # hits before counting a track

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # Reset lane statistics for this frame
            for lane in lane_stats:
                lane_stats[lane].clear()
                lane_stats[lane]['total'] = 0

            # Draw lane dividers
            for y in lane_heights:
                cv2.line(frame, (0, y), (width, y), (255, 255, 255), 2)

            # Perform YOLOv8 detection
            results = model(frame, conf=conf_global)
            
            total_this_frame = 0
            
            # Process detections
            if results and len(results) > 0:
                boxes = results[0].boxes
                # Collate detections by class with filtering
                detections_by_class = {name: [] for name in vehicle_colors.keys()}
                for box in boxes:
                    # Get box coordinates
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cls = int(box.cls[0])
                    conf = float(box.conf[0])

                    # Check if detected class is a vehicle we're interested in
                    if cls in class_map:
                        vehicle_type = class_map[cls]
                        color = vehicle_colors[vehicle_type]

                        # Per-class filtering to reduce false positives
                        conf_threshold = conf_global
                        if vehicle_type == 'motorcycle':
                            conf_threshold = motorcycle_conf  # be stricter for motorcycles
                        if conf < conf_threshold:
                            continue

                        # Filter implausibly large motorcycle boxes (often misclassifications)
                        box_area = max(1, (x2 - x1) * (y2 - y1))
                        if vehicle_type == 'motorcycle' and box_area > 0.05 * frame_area:
                            continue

                        detections_by_class[vehicle_type].append(((x1, y1, x2, y2), conf))

                # For each class, match detections to existing tracks
                for vtype, dets in detections_by_class.items():
                    # Age out stale tracks
                    fresh_tracks = []
                    for t in tracks[vtype]:
                        if frame_idx - t['last_seen'] <= TRACK_TIMEOUT:
                            fresh_tracks.append(t)
                    tracks[vtype] = fresh_tracks

                    used_det = set()
                    # Greedy match by IoU
                    for ti, t in enumerate(tracks[vtype]):
                        best_j = -1
                        best_iou = 0.0
                        for j, (dbox, dconf) in enumerate(dets):
                            if j in used_det:
                                continue
                            iou = _compute_iou(t['bbox'], dbox)
                            if iou > best_iou:
                                best_iou = iou
                                best_j = j
                        if best_j != -1 and best_iou >= iou_thresh:
                            # update track
                            tracks[vtype][ti]['bbox'] = dets[best_j][0]
                            tracks[vtype][ti]['last_seen'] = frame_idx
                            tracks[vtype][ti]['hits'] += 1
                            if not tracks[vtype][ti]['counted'] and tracks[vtype][ti]['hits'] >= CONFIRM_HITS:
                                unique_counts[vtype] += 1
                                tracks[vtype][ti]['counted'] = True
                            used_det.add(best_j)
                        
                    # Create tracks for unmatched detections
                    for j, (dbox, dconf) in enumerate(dets):
                        if j in used_det:
                            continue
                        tracks[vtype].append({
                            'id': next_track_id[vtype],
                            'bbox': dbox,
                            'last_seen': frame_idx,
                            'hits': 1,
                            'counted': False
                        })
                        next_track_id[vtype] += 1

                    # Count current concurrent for density
                    total_this_frame += len(dets)
                    # Confidence stats (accepted detections)
                    for _, dconf in dets:
                        accepted_conf_sum += dconf
                        accepted_conf_count += 1

                # Draw overlays from current tracks (latest bbox positions)
                for vtype, tlist in tracks.items():
                    color = vehicle_colors[vtype]
                    for t in tlist:
                        x1, y1, x2, y2 = t['bbox']
                        # Determine lane based on center point
                        center_y = (y1 + y2) // 2
                        if center_y < lane_heights[0]:
                            lane_name = 'Left Lane'
                        elif center_y < lane_heights[1]:
                            lane_name = 'Middle Lane'
                        else:
                            lane_name = 'Right Lane'
                        lane_stats[lane_name][vtype] += 1
                        lane_stats[lane_name]['total'] += 1

                        overlay = frame.copy()
                        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
                        cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        label = f"{vtype}"
                        label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                        cv2.rectangle(frame, (x1, y1 - label_size[1] - 10), (x1 + label_size[0], y1), color, -1)
                        cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

            if total_this_frame > max_total_concurrent:
                max_total_concurrent = total_this_frame

            # Record sampled density series
            if frame_idx % sample_every == 0:
                capacity = MAX_VEHICLES_PER_LANE * NUM_LANES
                density_pct = min(100.0, (total_this_frame / capacity) * 100.0)
                density_series.append(float(density_pct))

            # Draw lane statistics (overlay UI)
            for i, (lane_name, stats) in enumerate(lane_stats.items()):
                y_base = 30 + i * 120
                density = (stats['total'] / MAX_VEHICLES_PER_LANE) * 100
                density = min(density, 100)
                cv2.rectangle(frame, (10, y_base - 25), (250, y_base + 85), (0, 0, 0), -1)
                cv2.rectangle(frame, (10, y_base - 25), (250, y_base + 85), (255, 255, 255), 1)
                cv2.putText(frame, lane_name, (15, y_base), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                y_offset = 20
                for v_type in vehicle_colors:
                    count = stats[v_type]
                    cv2.putText(frame, f"{v_type.title()}: {count}", (20, y_base + y_offset),
                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, vehicle_colors[v_type], 1)
                    y_offset += 20
                bar_width = 200
                filled_width = int((bar_width * density) / 100)
                cv2.rectangle(frame, (20, y_base + 65), (20 + bar_width, y_base + 75), (100, 100, 100), 1)
                if density > 0:
                    if density > 75:
                        color = (0, 0, 255)
                    elif density > 50:
                        color = (0, 165, 255)
                    else:
                        color = (0, 255, 0)
                    cv2.rectangle(frame, (20, y_base + 65), (20 + filled_width, y_base + 75), color, -1)
                cv2.putText(frame, f"Density: {density:.1f}%", (25, y_base + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # Add frame counter
            cv2.putText(frame, f'Frame: {frame_count}', (10, height - 20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            out.write(frame)
            frame_count += 1
            frame_idx += 1

        # Release resources
        cap.release()
        out.release()

        if frame_count == 0:
            raise ValueError("No frames were processed from the video")

        # Compute overall density based on max concurrent vehicles vs capacity
        capacity = MAX_VEHICLES_PER_LANE * NUM_LANES
        density_percentage = min(100.0, (max_total_concurrent / capacity) * 100.0)
        avg_conf = (accepted_conf_sum / accepted_conf_count) if accepted_conf_count else 0.0
        low_confidence = avg_conf < 0.55

        results = {
            'total_vehicles': int(sum(unique_counts.values())),
            'density': float(density_percentage),
            'vehicle_counts': {
                'car': int(unique_counts['car']),
                'truck': int(unique_counts['truck']),
                'bus': int(unique_counts['bus']),
                'motorcycle': int(unique_counts['motorcycle'])
            },
            'density_series': density_series,
            'avg_confidence': float(avg_conf),
            'low_confidence': bool(low_confidence)
        }

        return results

    except Exception as e:
        import traceback
        print(f"Error processing video: {str(e)}")
        print(traceback.format_exc())
        raise e 