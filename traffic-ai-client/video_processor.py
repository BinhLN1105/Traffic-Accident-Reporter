import cv2
import argparse
import sys
import os
import json
import requests
import time
from collections import deque
from ultralytics import YOLO

# Constants
JAVA_BACKEND_URL = "http://localhost:8080/api/incidents/report"

def process_video(input_path, output_path, model_path='model/small/best.pt'):
    try:
        # Load Model
        model = YOLO(model_path)
    except Exception as e:
        print(f"Error loading model: {e}")
        return

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"Error opening video file: {input_path}")
        return

    # Video Writer
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Use standard MP4 codec (avc1/mp4v)
    # Java VideoController now supports .mp4
    try:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    except:
        print("Warning: mp4v codec failed, trying avc1")
        fourcc = cv2.VideoWriter_fourcc(*'avc1')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    print(f"Processing {input_path} -> {output_path}")

    # Metadata Tracking
    output_dir = os.path.dirname(output_path)
    base_name = os.path.splitext(os.path.basename(output_path))[0]
    metadata_path = os.path.join(output_dir, f"{base_name}.json")
    
    # Snapshot Paths
    snapshot_paths = []
    
    incidents = []
    
    # Snapshot Logic Init
    FPS = fps if fps > 0 else 30
    
    BEFORE_SECONDS = 3.0 # Capture 3 seconds before (User Request)
    AFTER_SECONDS = 3.5 

    BUFFER_SIZE = int(FPS * BEFORE_SECONDS)
    AFTER_FRAMES_COUNT = int(FPS * AFTER_SECONDS) # Capture 3.5 seconds after
    
    frame_buffer = deque(maxlen=BUFFER_SIZE)
    snapshot_state = 'SEARCHING' # SEARCHING -> CAPTURING_AFTER -> DONE
    frames_since_incident = 0
    
    current_best_conf = 0
    current_best_label = "accident"
    last_valid_frame = None
    
    # Assume 'Accident' is a specific class, or we treat certain classes as relevant.
    # For this demo, let's assume class 'accident' is detected, or we use a confidence threshold.
    # Adjust detected classes based on your trained model.
    # Common traffic classes: 0: car, 1: motorcycle, 2: bus, 3: truck...
    # If using a specific trained model for accidents, check model.names
    
    # print("Model Classes:", model.names) 

    while cap.isOpened():
        ret, frame = cap.read()
        
        # --- END OF VIDEO CHECK ---
        if not ret:
            print("End of video stream.")
            # Fallback: If waiting for 'After' shot, use last valid frame
            if snapshot_state == 'CAPTURING_AFTER' and last_valid_frame is not None:
                print("Video ended early. Forcing capture of AFTER snapshot.")
                path_after = os.path.join(output_dir, f"{base_name}_after.jpg")
                cv2.imwrite(path_after, last_valid_frame)
                snapshot_paths.append(path_after)
                print(f"Saved After (Fallback): {path_after}")
            break
            
        last_valid_frame = frame.copy()
        frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))

        # Inference
        results = model(frame, verbose=False)
        annotated_frame = results[0].plot()

        # Write frame
        out.write(annotated_frame)

        # Log progress
        if frame_idx % 30 == 0:
            print(f"Processed {frame_idx} frames...")
            sys.stdout.flush()

        # Add to buffer
        frame_buffer.append(frame.copy())

        # Log detection logic
        detection_found = False
        
        for result in results:
            for box in result.boxes:
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                label = model.names[cls]
                
                if conf > 0.5:
                    detection_found = True
                    timestamp = frame_idx / fps
                    
                    incidents.append({
                        "time": timestamp,
                        "label": label,
                        "confidence": conf
                    })
                    
                    # Snapshot State Machine
                    if snapshot_state == 'SEARCHING':
                         # If high confidence accident
                         if ("accident" in label.lower() or conf > 0.75):
                             print(f"[{frame_idx}] Accident Detected ({label} {conf:.2f}), capturing snapshots...")
                             
                             current_best_label = label
                             
                             # 1. Save BEFORE (oldest in buffer)
                             before_frame = frame_buffer[0] if frame_buffer else frame
                             path_before = os.path.join(output_dir, f"{base_name}_before.jpg")
                             cv2.imwrite(path_before, before_frame)
                             snapshot_paths.append(path_before)
                             print(f"Saved Before: {path_before}")
                             
                             # 2. Save DURING (current)
                             path_during = os.path.join(output_dir, f"{base_name}_during.jpg")
                             cv2.imwrite(path_during, frame)
                             snapshot_paths.append(path_during)
                             print(f"Saved During: {path_during}")
                             
                             snapshot_state = 'CAPTURING_AFTER'
                             frames_since_incident = 0

        # Handle 'CAPTURING_AFTER' State
        if snapshot_state == 'CAPTURING_AFTER':
            frames_since_incident += 1
            if frames_since_incident >= AFTER_FRAMES_COUNT:
                # 3. Save AFTER
                path_after = os.path.join(output_dir, f"{base_name}_after.jpg")
                cv2.imwrite(path_after, frame)
                snapshot_paths.append(path_after)
                print(f"Saved After: {path_after}")
                
                snapshot_state = 'DONE' # Limit to 1 incident sequence per batch logic for now

    cap.release()
    out.release()
    
    # Write Metadata JSON
    metadata = {
        "processed_video": output_path,
        "incidents": incidents,
        "snapshot_path": snapshot_paths[1] if len(snapshot_paths) > 1 else None, # Use 'during' as main
        "snapshot_paths": snapshot_paths,
        "has_accident": len(snapshot_paths) >= 3
    }
    
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=4)
        
    print(f"Metadata saved: {metadata_path}")
    
    # --- REPORT TO JAVA BACKEND ---
            # Ensure we have 3 snapshots (pad if necessary)
            while len(snapshot_paths) < 3:
                 # Fallback: duplicate last one or use placeholder
                 if snapshot_paths: snapshot_paths.append(snapshot_paths[-1])
                 else: break # Should not happen if snapshot_saved is true
            
            with open(snapshot_paths[0], 'rb') as f_before:
                with open(snapshot_paths[1], 'rb') as f_during:
                    with open(snapshot_paths[2], 'rb') as f_after:
                        with open(output_path, 'rb') as f_vid:
                            
                            files = {
                                'imageBefore': ('before.jpg', f_before, 'image/jpeg'),
                                'imageDuring': ('during.jpg', f_during, 'image/jpeg'),
                                'imageAfter':  ('after.jpg', f_after, 'image/jpeg'),
                                'video':       ('video.mp4', f_vid, 'video/mp4')
                            }
                    
                    # Determine label
                    top_label = incidents[0]['label'] if incidents else "vehicle accident"
                    
                    data = {
                        'type': top_label,
                        'description': "Auto-detected by Batch Analysis", 
                    }
                    
                    # POST
                    res = requests.post(JAVA_BACKEND_URL, files=files, data=data)
                    
                    if res.status_code == 200:
                        print(f"✅ Reported to Backend! ID: {res.json().get('id')}")
                    else:
                        print(f"❌ Report Failed: {res.status_code} {res.text}")
                        
        except Exception as e:
            print(f"Error reporting to backend: {e}")

    print("Processing Complete.")
    sys.stdout.flush()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input video path")
    parser.add_argument("--output", required=True, help="Output video path")
    # Optional: model path if needed to override
    args = parser.parse_args()

    process_video(args.input, args.output)
