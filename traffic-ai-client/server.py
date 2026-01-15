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
import requests # Added for API calls

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

def process_video_task(input_path, output_path, job_id, is_realtime, model_type="medium", custom_labels="accident, vehicle accident", confidence_threshold=0.70, auto_report=True):
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
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps == 0 or fps is None:
            fps = 30  # Fallback only if invalid
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        print(f"[{job_id}] Video Info: FPS={fps}, Frames={total_frames}, Size={width}x{height}")
        
        # Use WebM format with VP8 codec for browser compatibility
        if output_path.endswith('.avi'):
            output_path = output_path.replace('.avi', '.webm')
        elif output_path.endswith('.mp4'):
            output_path = output_path.replace('.mp4', '.webm')
        
        # Normalize FPS to 30 for WebM (some codecs don't handle non-standard FPS well)
        # Compensate for 2x playback issue by halving the FPS
        output_fps = fps / 2.0 if fps > 0 else 15.0
        print(f"[{job_id}] Writing video at {output_fps} FPS (compensated)")
        fourcc = cv2.VideoWriter_fourcc(*'VP80')
        out = cv2.VideoWriter(output_path, fourcc, output_fps, (width, height))

        incidents = []
        frame_count = 0
        
        # Snapshot Configuration - Use ACTUAL FPS
        BEFORE_SECONDS = 3
        AFTER_SECONDS = 3.5
        BUFFER_SIZE = int(fps * BEFORE_SECONDS)
        AFTER_FRAMES = int(fps * AFTER_SECONDS)

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
            ret, frame = cap.read()
            
            # --- END OF VIDEO CHECK ---
            if not ret:
                 print(f"[{job_id}] End of video stream.")
                 # Fallback: Capture AFTER if pending
                 if snapshot_state == 'CAPTURING_AFTER':
                     print(f"[{job_id}] Video ended early. Forcing capture of AFTER snapshot.")
                     after_path = os.path.join(DATA_DIR, f"{job_id}_after.jpg")
                     # Use last valid frame if available, else current (which is None, so careful)
                     # Since ret is False, frame is None. Use frame_buffer[-1] or last processed
                     if frame_buffer:
                         cv2.imwrite(after_path, frame_buffer[-1])
                         snapshot_paths.append(after_path)
                 break
            
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
                            if snapshot_state == 'SEARCHING':
                                # If high confidence accident
                                if ("accident" in label.lower() or conf > 0.70):
                                    current_incident_label = label
                                    print(f"[{job_id}] Accident Detected ({label} {conf:.2f}), capturing snapshots...")
                                    
                                    # 1. Save BEFORE (oldest in buffer)
                                    before_frame = frame_buffer[0] if frame_buffer else frame
                                    before_path = os.path.join(DATA_DIR, f"{job_id}_before.jpg")
                                    cv2.imwrite(before_path, before_frame)
                                    snapshot_paths.append(before_path)
                                    
                                    # 2. Save DURING (current)
                                    during_path = os.path.join(DATA_DIR, f"{job_id}_during.jpg")
                                    cv2.imwrite(during_path, frame)
                                    snapshot_paths.append(during_path)
                                    
                                    snapshot_state = 'CAPTURING_AFTER'
                                    frames_since_incident = 0

            else:
                annotated_frame = frame

            out.write(annotated_frame)
            
            # --- SNAPSHOT STATE MACHINE ---
            # --- SNAPSHOT STATE MACHINE ---
            # SEARCHING logic is handled inside Detection Loop above

            if snapshot_state == 'CAPTURING_AFTER':
                frames_since_incident += 1
                if frames_since_incident >= (fps * 3.5): # 3.5 sec after
                    # 3. Save AFTER
                    after_path = os.path.join(DATA_DIR, f"{job_id}_after.jpg")
                    cv2.imwrite(after_path, frame)
                    snapshot_paths.append(after_path)
                    
                    snapshot_state = 'DONE'
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
        
        # --- REPORT TO JAVA BACKEND ---
        # --- REPORT TO JAVA BACKEND ---
        # Ensure 3 snapshots (Pad if missing)
        while len(snapshot_paths) < 3 and len(snapshot_paths) > 0:
             snapshot_paths.append(snapshot_paths[-1])
             
        if auto_report and len(snapshot_paths) >= 3:
             print(f"[{job_id}] Auto-report enabled. Sending to backend...")
             report_to_backend(snapshot_paths, incidents[0]['label'] if incidents else "accident", output_path)
        elif not auto_report:
             print(f"[{job_id}] Auto-report disabled. Skipping backend reporting.")

    except Exception as e:
        print(f"[{job_id}] Error: {str(e)}")
        jobs[job_id]['status'] = 'FAILED'
        jobs[job_id]['message'] = str(e)


def report_to_backend(snapshot_paths, label, video_path=None):
    """
    Send the 3 snapshots + metadata + optional video to the Java Backend
    Endpoint: POST http://localhost:8080/api/incidents/report
    Params: imageBefore, imageDuring, imageAfter, type, description, video
    """
    API_URL = "http://localhost:8080/api/incidents/report"
    
    try:
        print(f"Uploading incident '{label}' to Backend...")
        
        files = {
            'imageBefore': open(snapshot_paths[0], 'rb'),
            'imageDuring': open(snapshot_paths[1], 'rb'),
            'imageAfter': open(snapshot_paths[2], 'rb'),
        }
        
        if video_path and os.path.exists(video_path):
            files['video'] = open(video_path, 'rb')
        
        data = {
            'type': label,
            'description': f"Auto-detected {label} by Python Analysis Server"
        }
        
        response = requests.post(API_URL, files=files, data=data)
        
        # Close files
        for f in files.values():
            f.close()
            
        if response.status_code == 200:
            print("✅ Successfully reported to Backend. ID:", response.json().get('id'))
        else:
            print(f"❌ Backend Report Failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error reporting to backend: {str(e)}")


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
    
    # Handle autoReport as either boolean or string
    auto_report_value = data.get('autoReport', True)
    if isinstance(auto_report_value, bool):
        auto_report = auto_report_value
    else:
        auto_report = str(auto_report_value).lower() == 'true'
    
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
        worker = threading.Thread(target=process_video_task, args=(input_path, output_path, job_id, False, model_type, custom_labels, confidence_threshold, auto_report))
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
