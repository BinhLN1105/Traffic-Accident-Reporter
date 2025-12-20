from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import uuid
import sys
import os
import cv2
from ultralytics import YOLO

app = Flask(__name__)
CORS(app)

# In-memory job store
jobs = {}

# Load Model Once
MODEL_PATH = "model/small/best.pt"
print(f"Loading Model from {MODEL_PATH}...")
model = YOLO(MODEL_PATH) 
print("Model Loaded!")

def process_video_task(job_id, input_path, output_path):
    print(f"[{job_id}] Starting processing: {input_path} -> {output_path}")
    jobs[job_id]['status'] = 'PROCESSING'
    jobs[job_id]['progress'] = 0

    try:
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception("Cannot open video file")

        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps    = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Use VP80 codec (.webm) for best browser compatibility
        fourcc_code = 'VP80'
        try:
            fourcc = cv2.VideoWriter_fourcc(*fourcc_code)
            # Ensure output file ends in .webm if using VP80, but Java handles filename.
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        except:
             # Fallback
            print("VP80 codec failed, falling back to mp4v")
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        from collections import deque
        frame_buffer = deque(maxlen=60) # Buffer ~2 seconds (at 30fps)
        
        frame_count = 0
        incidents = []
        
        # Snapshot state
        snapshot_saved_during = False
        snapshot_paths = []
        
        # Logic for "After" snapshot
        frames_since_incident = -1 
        TRIGGER_AFTER_FRAMES = 60 # Capture "After" ~2 seconds later
        
        base_filename = os.path.splitext(output_path)[0]
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
                
            # Maintain buffer
            frame_buffer.append(frame.copy())

            # AI Detection
            results = model(frame, verbose=False)
            annotated_frame = results[0].plot()

            # --- Incident Detection Logic ---
            current_frame_is_incident = False
            for result in results:
                for box in result.boxes:
                    conf = float(box.conf[0])
                    if conf > 0.5:
                        cls_id = int(box.cls[0])
                        label = model.names[cls_id]
                        timestamp = frame_count / fps 

                        incidents.append({
                            "time": timestamp,
                            "label": label,
                            "confidence": conf
                        })
                        
                        # FIX: Only trigger on ACTUAL accident labels. 
                        # Removed 'or conf > 0.7' which was falsely triggering on normal cars.
                        if "accident" in label.lower() or "crash" in label.lower() or "collision" in label.lower():
                            current_frame_is_incident = True

            # SNAPSHOT LOGIC
            # 1. Trigger Incident (First time) pattern
            if current_frame_is_incident and not snapshot_saved_during:
                print(f"[{job_id}] Incident Detected! capturing sequence...")
                snapshot_saved_during = True
                
                # A. Save BEFORE (from buffer start)
                if len(frame_buffer) > 0:
                    path_before = f"{base_filename}_1_before.jpg"
                    cv2.imwrite(path_before, frame_buffer[0]) # Oldest frame
                    snapshot_paths.append(path_before)
                
                # B. Save DURING (current)
                path_during = f"{base_filename}_2_during.jpg"
                cv2.imwrite(path_during, frame)
                snapshot_paths.append(path_during)
                
                # Start counter for AFTER
                frames_since_incident = 0
            
            # 2. Count for AFTER
            if snapshot_saved_during and frames_since_incident >= 0:
                frames_since_incident += 1
                if frames_since_incident == TRIGGER_AFTER_FRAMES:
                    # C. Save AFTER
                    path_after = f"{base_filename}_3_after.jpg"
                    cv2.imwrite(path_after, frame)
                    snapshot_paths.append(path_after)
                    print(f"[{job_id}] Sequence capture complete.")
            # --------------------------------

            out.write(annotated_frame)
            frame_count += 1
            
            # Update Progress
            progress = int((frame_count / total_frames) * 100)
            jobs[job_id]['progress'] = progress
            
            if frame_count % 30 == 0:
                print(f"[{job_id}] Progress: {progress}%")

        cap.release()
        out.release()
        
        # Save Metadata JSON for Java to read
        import json
        metadata = {
            "has_accident": len(snapshot_paths) > 0, 
            "snapshot_path": snapshot_paths[0] if snapshot_paths else None, # Legacy support
            "snapshot_paths": snapshot_paths, # New list
            "incidents": incidents
        }
        
        # safely replace extension
        if output_path.endswith('.webm'):
             json_path = output_path[:-5] + ".json"
        elif output_path.endswith('.mp4'):
             json_path = output_path[:-4] + ".json"
        else:
             json_path = output_path + ".json"
             
        with open(json_path, 'w') as f:
            json.dump(metadata, f, indent=4)

        jobs[job_id]['status'] = 'COMPLETED'
        jobs[job_id]['progress'] = 100
        print(f"[{job_id}] Finished. Metadata saved to {json_path}")

    except Exception as e:
        print(f"[{job_id}] Error: {str(e)}")
        jobs[job_id]['status'] = 'FAILED'
        jobs[job_id]['message'] = str(e)


@app.route('/process', methods=['POST'])
def process_video():
    data = request.json
    input_path = data.get('inputPath')
    output_path = data.get('outputPath')

    if not input_path or not output_path:
        return jsonify({"error": "Missing inputPath or outputPath"}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "id": job_id,
        "status": "QUEUED",
        "progress": 0
    }

    # Start Thread
    thread = threading.Thread(target=process_video_task, args=(job_id, input_path, output_path))
    thread.daemon = True
    thread.start()

    return jsonify({"jobId": job_id, "status": "QUEUED"})

@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

if __name__ == '__main__':
    # Run on 0.0.0.0 to verify visibility, port 5000
    app.run(host='0.0.0.0', port=5000, debug=False)
