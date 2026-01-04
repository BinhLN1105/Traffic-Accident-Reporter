from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import uuid
import sys
import os
import cv2
import time
import asyncio
import json
import logging
import shutil

from ultralytics import YOLO
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame

app = Flask(__name__)
CORS(app)

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

# Global Model Cache
MODELS = {}
MODEL_PATHS = {
    "small": "model/small/best.pt",
    "medium": "model/medium/best.pt",
    "mediumv2": "model/medium/mediumv2.pt",
    "mediumv3": "model/medium/mediumv3.pt"
}

def get_model(model_type="medium"):
    """
    Retrieves the requested YOLO model, loading it if necessary.
    Defaults to 'medium' if model_type is invalid or not specified.
    """
    model_type = str(model_type).lower()
    if model_type not in MODEL_PATHS:
        print(f"Warning: Unknown model type '{model_type}'. Defaulting to 'medium'.")
        model_type = "medium"
    
    if model_type not in MODELS:
        print(f"Loading '{model_type}' model from {MODEL_PATHS[model_type]}...")
        MODELS[model_type] = YOLO(MODEL_PATHS[model_type])
        print(f"Model '{model_type}' loaded successfully.")
    
    return MODELS[model_type]

# Initialize default model
get_model("medium")

# Job Store
jobs = {}
pcs = set()

# --- BATCH WORKER ---
from collections import deque

def process_video_task(input_path, output_path, job_id, is_realtime, model_type="medium", custom_labels="accident, vehicle accident", confidence_threshold=0.70):
    try:
        jobs[job_id]['status'] = 'PROCESSING'
        
        # Parse custom labels
        target_labels = [l.strip().lower() for l in custom_labels.split(',') if l.strip()]
        print(f"[{job_id}] Target Labels: {target_labels} | Conf Threshold: {confidence_threshold}")

        model = get_model(model_type)

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception("Cannot open video file")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        fourcc = cv2.VideoWriter_fourcc(*'vp80') 
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        incidents = []
        frame_count = 0
        
        # Snapshot Configuration
        FPS = 30
        BEFORE_SECONDS = 3
        AFTER_SECONDS = 3
        BUFFER_SIZE = FPS * BEFORE_SECONDS
        AFTER_FRAMES = FPS * AFTER_SECONDS

        frame_buffer = deque(maxlen=BUFFER_SIZE) 
        snapshot_state = 'SEARCHING'
        frames_since_incident = 0
        consecutive_accident_frames = 0 # Temporal consistency counter
        snapshot_paths = []
        
        # Data dir
        DATA_DIR = os.path.dirname(output_path)
        if not os.path.exists(DATA_DIR):
             try: os.makedirs(DATA_DIR)
             except: pass
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            # Add to buffer (save raw frame for snapshots)
            frame_buffer.append(frame.copy())

            # Inference
            results = model(frame, verbose=False)
            current_incident_label = None
            current_conf = 0
            
            if results:
                annotated_frame = results[0].plot()
                
                # Detect Incidents
                for result in results:
                    for box in result.boxes:
                        conf = float(box.conf[0])
                        cls_id = int(box.cls[0])
                        label = model.names[cls_id]
                        
                        # Filter by custom labels
                        if label.lower() in target_labels and conf > 0.5:
                            incidents.append({
                                "time": frame_count / fps,
                                "label": label,
                                "confidence": conf
                            })
                            
                            # Snapshot logic: use dynamic confidence_threshold
                            if conf >= confidence_threshold:
                                consecutive_accident_frames += 1
                            else:
                                consecutive_accident_frames = 0
                            
                            # Use state check instead of missing flag
                            if snapshot_state == 'SEARCHING' and consecutive_accident_frames >= 5:
                                current_incident_label = label
                                current_conf = conf

            else:
                annotated_frame = frame

            out.write(annotated_frame)
            
            # --- SNAPSHOT STATE MACHINE ---
            if snapshot_state == 'SEARCHING':
                if current_incident_label:
                    print(f"[{job_id}] EVENT DETECTED: {current_incident_label}")
                    snapshot_state = 'CAPTURING_AFTER'
                    frames_since_incident = 0
                    
                    # 1. Save BEFORE (oldest in buffer)
                    if len(frame_buffer) > 0:
                        before_path = os.path.join(DATA_DIR, f"{job_id}_before.jpg")
                        cv2.imwrite(before_path, frame_buffer[0])
                        snapshot_paths.append(before_path)
                    
                    # 2. Save DURING (current)
                    during_path = os.path.join(DATA_DIR, f"{job_id}_during.jpg")
                    cv2.imwrite(during_path, frame)
                    snapshot_paths.append(during_path)
                    
            elif snapshot_state == 'CAPTURING_AFTER':
                frames_since_incident += 1
                if frames_since_incident >= 90: # ~3 sec after
                    # 3. Save AFTER
                    after_path = os.path.join(DATA_DIR, f"{job_id}_after.jpg")
                    cv2.imwrite(after_path, frame)
                    snapshot_paths.append(after_path)
                    
                    snapshot_state = 'DONE' # Limit to 1 sequence per video for now
                    print(f"[{job_id}] Snapshot sequence complete.")

            frame_count += 1
            
            # Update Progress
            if total_frames > 0:
                progress = int((frame_count / total_frames) * 100)
                jobs[job_id]['progress'] = progress
            
            if frame_count % 30 == 0:
                print(f"[{job_id}] Progress: {jobs[job_id]['progress']}%")

        cap.release()
        out.release()
        
        # Save Metadata
        metadata = {
            "has_accident": len(incidents) > 0, 
            "snapshot_paths": snapshot_paths,
            "incidents": incidents
        }
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


# --- GLOBAL ASYNC LOOP SETUP (WEBRTC) ---
loop = asyncio.new_event_loop()

def start_loop():
    asyncio.set_event_loop(loop)
    loop.run_forever()

t = threading.Thread(target=start_loop, daemon=True)
t.start()
# -------------------------------

class YoloVideoTrack(VideoStreamTrack):
    # ... [Same as before] ...
    def __init__(self, video_path):
        super().__init__()
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
             logger.error(f"Cannot open video: {video_path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        ret, frame = self.cap.read()
        if not ret:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()
            if not ret: return
        
        results = model(frame, verbose=False)
        annotated_frame = results[0].plot()
        frame_rgb = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
        
        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

    def stop(self):
        if self.cap: self.cap.release()
        super().stop()


@app.route('/process', methods=['POST'])
def process_video():
    data = request.json
    print(f"DEBUG: Received /process request: {data}")
    
    input_path = data.get('inputPath')
    output_path = data.get('outputPath') # Optional for Realtime, Required for Batch
    is_realtime = data.get('realtime', False)
    model_type = data.get('modelType', 'medium') # Default to medium
    custom_labels = data.get('customLabels', 'accident, vehicle accident')
    confidence_threshold = float(data.get('confidenceThreshold', 0.70))
    
    if not input_path:
        return jsonify({"error": "Missing inputPath"}), 400

    job_id = str(uuid.uuid4())
    
    if is_realtime:
        # REALTIME JOB
        jobs[job_id] = {
            "id": job_id,
            "inputPath": input_path,
            "type": "REALTIME",
            "status": "READY",
            "modelType": model_type
        }
    else:
        # BATCH JOB
        if not output_path:
             # Genererate default if missing? 
             # But Java should send it.
             return jsonify({"error": "Missing outputPath for batch mode"}), 400

        jobs[job_id] = {
            "id": job_id,
            "type": "BATCH",
            "status": "QUEUED",
            "progress": 0,
            "modelType": model_type,
            "customLabels": custom_labels,
            "confidenceThreshold": confidence_threshold
        }
        
        # Start Thread
        worker = threading.Thread(target=process_video_task, args=(input_path, output_path, job_id, False, model_type, custom_labels, confidence_threshold))
        worker.daemon = True
        worker.start()

    return jsonify({"jobId": job_id, "status": "READY" if is_realtime else "QUEUED"})

@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

# Logic to run inside the global loop (WebRTC Offer)
async def run_offer(params):
    # ... [Same as before] ...
    offer_sdp = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    job_id = params.get("jobId")
    job = jobs.get(job_id)
    if not job: raise Exception("Job not found")
        
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state is {pc.connectionState}")
        if pc.connectionState in ["failed", "closed"]:
            await pc.close()
            pcs.discard(pc)

    if os.path.exists(job["inputPath"]):
        video_track = YoloVideoTrack(job["inputPath"])
        pc.addTrack(video_track)
    else:
        print(f"ERROR: File not found {job['inputPath']}")

    await pc.setRemoteDescription(offer_sdp)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return { "sdp": pc.localDescription.sdp, "type": pc.localDescription.type }

@app.route('/offer', methods=['POST'])
def offer():
    params = request.json
    try:
        future = asyncio.run_coroutine_threadsafe(run_offer(params), loop)
        result = future.result(timeout=10)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Offer failed: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
