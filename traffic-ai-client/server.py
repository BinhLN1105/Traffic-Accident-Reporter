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
    "medium": "model/medium/best.pt"
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

def process_video_task(job_id, input_path, output_path, model_type="medium"):
    print(f"[{job_id}] Starting BATCH processing: {input_path} -> {output_path} (Model: {model_type})")
    jobs[job_id]['status'] = 'PROCESSING'
    jobs[job_id]['progress'] = 0
    
    try:
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception("Cannot open video file")

        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps    = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Codec
        fourcc_code = 'VP80'
        try:
            fourcc = cv2.VideoWriter_fourcc(*fourcc_code)
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        except:
            print("VP80 codec failed, falling back to mp4v")
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        # Variables for analysis
        frame_count = 0
        incidents = []
        
        # Snapshot Logic: Before, During, After
        frame_buffer = deque(maxlen=100) # ~3.3 sec buffer
        snapshot_state = 'SEARCHING' # SEARCHING -> CAPTURING_AFTER -> DONE
        frames_since_incident = 0
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
            model = get_model(model_type)
            results = model(frame, verbose=False)
            current_incident_label = None
            current_conf = 0
            
            if results:
                annotated_frame = results[0].plot()
                
                # Detect Incidents
                for result in results:
                    for box in result.boxes:
                        conf = float(box.conf[0])
                        if conf > 0.5:
                            cls_id = int(box.cls[0])
                            label = model.names[cls_id]
                            incidents.append({
                                "time": frame_count / fps,
                                "label": label,
                                "confidence": conf
                            })
                            
                            # Snapshot logic: STRICTER condition
                            # Capture 'accident' or 'vehicle accident' with high confidence (> 0.70)
                            # 0.70 allows capturing the "vehicle accident 0.72" case while avoiding low conf noise
                            is_accident = "accident" in label.lower() or "vehicle accident" in label.lower()
                            
                            # Use state check instead of missing flag
                            if snapshot_state == 'SEARCHING' and is_accident and conf >= 0.70:
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
            "modelType": model_type
        }
        
        # Start Thread
        worker = threading.Thread(target=process_video_task, args=(job_id, input_path, output_path, model_type))
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
