from flask import Flask, request, jsonify, send_from_directory
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
import tempfile # For Temp Dir logic

from ultralytics import YOLO
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame

app = Flask(__name__)
CORS(app)

# Thiết lập ghi log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

# Global Model Cache
MODELS = {}
MODEL_PATHS = {
    "small": "model/small/best.pt",
    "medium": "model/medium/mediumv1.pt"
}

# Define Global Temp Data Root for Stream
STREAM_DATA_ROOT = os.path.join(tempfile.gettempdir(), 'traffic_ai_data')
os.makedirs(STREAM_DATA_ROOT, exist_ok=True)
print(f"Stream Data Root: {STREAM_DATA_ROOT}")

def get_model(model_type="medium"):
    """
    Lấy mô hình YOLO được yêu cầu, tải nó nếu cần thiết.
    Mặc định là 'medium' nếu model_type không hợp lệ hoặc không được chỉ định.
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

# Khởi tạo mô hình mặc định
get_model("medium")

# Kho lưu trữ thông tin công việc (Job Store)
jobs = {}
pcs = set()

# --- BATCH WORKER ---
# --- XỬ LÝ BATCH (HÀNG LOẠT) ---
from collections import deque
import datetime

def draw_styled_box(img, x1, y1, x2, y2, label, conf, color):
    # Box
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
    
    # Nhãn có nền
    text = f"{label} {conf:.2f}"
    font_scale = 0.8
    thickness = 2
    (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    
    cv2.rectangle(img, (x1, y1 - 25), (x1 + w, y1), color, -1)
    cv2.putText(img, text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), thickness)

def add_timestamp(img, seconds):
    time_str = str(datetime.timedelta(seconds=int(seconds)))
    cv2.putText(img, f"Time: {time_str}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4) # Outline
    cv2.putText(img, f"Time: {time_str}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2) # Text

def process_video_task(input_path, output_path, job_id, is_realtime, model_type="medium", custom_labels="accident, vehicle accident", confidence_threshold=0.70, auto_report=True):
    try:
        jobs[job_id]['status'] = 'PROCESSING'
        
        # Phân tích các nhãn tùy chỉnh
        target_labels = [l.strip().lower() for l in custom_labels.split(',') if l.strip()]
        print(f"[{job_id}] Target Labels: {target_labels} | Conf: {confidence_threshold}")

        model = get_model(model_type)

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception("Cannot open video file")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Cấu hình video đầu ra
        output_fps = fps if fps > 0 else 30.0
        fourcc = cv2.VideoWriter_fourcc(*'VP80') # Định dạng WebM
        out = cv2.VideoWriter(output_path, fourcc, output_fps, (width, height))

        # --- CẤU HÌNH TỐI ƯU ---
        FRAME_SKIP = 3  # Nhảy cóc 3 frame để tăng tốc
        last_boxes = [] # Cache vẽ hình
        
        # --- CẤU HÌNH SNAPSHOT & XÁC NHẬN ---
        BEFORE_SECONDS = 4.0
        AFTER_SECONDS = 5.0
        BUFFER_SIZE = int(fps * BEFORE_SECONDS)
        
        # Xác thực tai nạn (Kiểm tra độ bền vững)
        ACCIDENT_DURATION_THRESHOLD = 0.5 
        CONFIRMATION_FRAMES = int(fps * ACCIDENT_DURATION_THRESHOLD)
        current_accident_streak = 0 
        
        frame_buffer = deque(maxlen=BUFFER_SIZE) 
        snapshot_state = 'SEARCHING'
        frames_since_incident = 0
        snapshot_paths = [] # Danh sách ảnh chụp sự cố hiện tại
        all_snapshot_paths = [] # TẤT CẢ ảnh chụp sự cố (cho frontend)
        
        detected_accidents = []
        current_incident_info = None
        incidents = []
        all_reports = [] # Lưu trữ tất cả báo cáo AI
        
        # Tạo thư mục data nếu chưa có
        DATA_DIR = os.path.dirname(output_path)
        os.makedirs(DATA_DIR, exist_ok=True)
        
        frame_count = 0
        
        # Theo dõi phương án dự phòng (Fallback)
        best_fallback_conf = 0.0
        best_fallback_data = None # (nhãn, frame_trước, frame_trong)
        
        while cap.isOpened():
            ret, frame = cap.read() # Chỉ giữ 1 dòng read
            
            if not ret:
                print(f"[{job_id}] End of video stream.")
                # BẮT BUỘC CHỤP ẢNH HOÀN THÀNH NẾU ĐANG CHỜ
                if snapshot_state == 'CAPTURING_AFTER':
                    print(f"[{job_id}] Video ended before 'After' frame. Forcing capture.")
                    after_path = os.path.join(DATA_DIR, f"{job_id}_{frame_count}_after.jpg")
                    
                    # Chụp & Đóng dấu thời gian
                    final_after = frame_buffer[-1].copy() if frame_buffer else (last_boxes[0] if last_boxes else None) # Dự phòng lấy cái gì đó
                    if final_after is None: # Trường hợp cực đoan
                         final_after = np.zeros((height, width, 3), dtype=np.uint8)

                    add_timestamp(final_after, frame_count / fps)
                    cv2.imwrite(after_path, final_after)
                    
                    snapshot_paths.append(after_path)
                    all_snapshot_paths.append(after_path)
                    
                    # reports_data = [] # REMOVED local init
                    # REPORT NGAY LẬP TỨC
                    if auto_report and current_incident_info:
                        report_result = report_to_backend(snapshot_paths, current_incident_info['label'], output_path)
                        if report_result:
                            all_reports.append(report_result)
                            current_incident_info['aiReport'] = report_result.get('aiReport')
                            
                    detected_accidents.append({
                        "timestamp": current_incident_info['time'],
                        "label": current_incident_info['label'],
                        "snapshots": list(snapshot_paths)
                    })

                break
            
            frame_buffer.append(frame.copy())
            
            detection_found_in_this_frame = False
            current_frame_label = ""
            current_frame_conf = 0.0

            # --- LOGIC FRAME SKIPPING ---
            if frame_count % FRAME_SKIP == 0:
                # Chạy AI (có imgsz=640 để tối ưu)
                results = model.track(frame, persist=True, imgsz=640, verbose=False, tracker="bytetrack.yaml")
                
                last_boxes = [] # Xóa cache cũ
                
                if results:
                    for result in results:
                        for box in result.boxes:
                            coords = tuple(map(int, box.xyxy[0]))
                            conf = float(box.conf[0])
                            cls_id = int(box.cls[0])
                            label = model.names[cls_id]
                            
                            last_boxes.append((coords, label, conf))
                            
                            # Kiểm tra label và độ tin cậy
                            if label.lower() in target_labels and conf > confidence_threshold:
                                detection_found_in_this_frame = True
                                current_frame_label = label
                                current_frame_conf = conf
                                
                                # Update Fallback Candidate
                                if conf > best_fallback_conf:
                                    best_fallback_conf = conf
                                    fb_before = frame_buffer[0].copy() if frame_buffer else frame.copy()
                                    
                                    # LOGIC TUA NGƯỢC CHO CẢ DỰ PHÒNG
                                    # Ngay cả khi dự phòng, chúng ta muốn khung hình từ 1.5s trước đó nếu có thể
                                    f_rewind_s = 1.5
                                    f_frames_back = int(fps * f_rewind_s)
                                    if len(frame_buffer) > f_frames_back:
                                        fb_during = frame_buffer[-f_frames_back].copy()
                                    elif frame_buffer:
                                        fb_during = frame_buffer[0].copy()
                                    else:
                                        fb_during = frame.copy()
                                        
                                    best_fallback_data = (label, fb_before, fb_during)

            else:
                # Dùng lại kết quả từ cache (Skip frame)
                for box_data in last_boxes:
                    (coords, label, conf) = box_data
                    if label.lower() in target_labels and conf > confidence_threshold:
                        detection_found_in_this_frame = True
                        current_frame_label = label
                        current_frame_conf = conf

            # --- VẼ HÌNH ---
            annotated_frame = frame.copy()
            
            # Timestamp cho video
            add_timestamp(annotated_frame, frame_count / fps)
            
            for box_data in last_boxes:
                (coords, label, conf) = box_data
                x1, y1, x2, y2 = coords
                color = (0, 0, 255) if label.lower() in target_labels else (0, 255, 0)
                draw_styled_box(annotated_frame, x1, y1, x2, y2, label, conf, color)

            # --- LOGIC XÁC NHẬN TAI NẠN (Persistence) ---
            if detection_found_in_this_frame:
                incidents.append({
                    "time": frame_count / fps,
                    "label": current_frame_label,
                    "confidence": current_frame_conf
                })
                current_accident_streak += 1
                
                if snapshot_state == 'SEARCHING':
                    if current_accident_streak >= CONFIRMATION_FRAMES:
                        print(f"[{job_id}] 🚨 Accident CONFIRMED (Streak: {current_accident_streak}), capturing...")
                        current_incident_info = incidents[-1]
                        
                        # 1. Lưu TRƯỚC (BEFORE)
                        before_frame = frame_buffer[0].copy() if frame_buffer else frame.copy()
                        add_timestamp(before_frame, (frame_count - len(frame_buffer)) / fps if frame_buffer else frame_count/fps)
                        before_path = os.path.join(DATA_DIR, f"{job_id}_{frame_count}_before.jpg")
                        cv2.imwrite(before_path, before_frame)
                        snapshot_paths = [before_path] # Reset for new incident
                        all_snapshot_paths.append(before_path)
                        
                        # 2. Lưu TRONG KHI (DURING) - (LOGIC TUA NGƯỢC)
                        # Thay vì lấy frame hiện tại, quay lại 0.5s để bắt khoảnh khắc va chạm
                        SECONDS_TO_REWIND = 0.5  
                        frames_back = int(fps * SECONDS_TO_REWIND)
                        
                        if len(frame_buffer) > frames_back:
                            during_frame = frame_buffer[-frames_back].copy()
                        elif frame_buffer:
                             during_frame = frame_buffer[0].copy()
                        else:
                             during_frame = frame.copy()

                        add_timestamp(during_frame, frame_count / fps)
                        during_path = os.path.join(DATA_DIR, f"{job_id}_{frame_count}_during.jpg")
                        cv2.imwrite(during_path, during_frame)
                        snapshot_paths.append(during_path)
                        all_snapshot_paths.append(during_path)
                        
                        snapshot_state = 'CAPTURING_AFTER'
                        frames_since_incident = 0
            else:
                current_accident_streak = 0

            # --- VISUAL DEBUG ---
            if current_accident_streak > 0 and snapshot_state == 'SEARCHING':
                bar_width = min(int((current_accident_streak / CONFIRMATION_FRAMES) * 200), 200)
                cv2.rectangle(annotated_frame, (50, 50), (50 + 200, 70), (255, 255, 255), 2)
                cv2.rectangle(annotated_frame, (50, 50), (50 + bar_width, 70), (0, 0, 255), -1)
                cv2.putText(annotated_frame, "CONFIRMING...", (50, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            out.write(annotated_frame)

            # --- XỬ LÝ CHỤP ẢNH SAU & BÁO CÁO ---
            if snapshot_state == 'CAPTURING_AFTER':
                frames_since_incident += 1
                if frames_since_incident >= (fps * AFTER_SECONDS): # Chụp ảnh SAU theo cấu hình giây
                    # 3. Lưu SAU (AFTER)
                    after_path = os.path.join(DATA_DIR, f"{job_id}_{frame_count}_after.jpg")
                    
                    # Đóng dấu thời gian cho ảnh SAU
                    final_after = frame.copy()
                    add_timestamp(final_after, frame_count / fps)
                    
                    cv2.imwrite(after_path, final_after)
                    snapshot_paths.append(after_path)
                    all_snapshot_paths.append(after_path)
                    
                    # reports_data = [] # REMOVED local init
                    # REPORT NGAY LẬP TỨC
                    if auto_report and current_incident_info:
                        report_result = report_to_backend(snapshot_paths, current_incident_info['label'], output_path)
                        if report_result:
                            all_reports.append(report_result)
                            # Đính kèm vào thông tin sự cố để dự phòng
                            current_incident_info['aiReport'] = report_result.get('aiReport')
                    
                    detected_accidents.append({
                        "timestamp": current_incident_info['time'],
                        "label": current_incident_info['label'],
                        "snapshots": list(snapshot_paths)
                    })
                    
                    snapshot_state = 'COOLDOWN'
                    frames_since_incident = 0
            
            # Cooldown logic
            if snapshot_state == 'COOLDOWN':
                frames_since_incident += 1
                if frames_since_incident >= (fps * 5.0):
                    snapshot_state = 'SEARCHING'
                    current_accident_streak = 0

            frame_count += 1
            
            # Cập nhật tiến độ mỗi 30 frame
            if total_frames > 0 and frame_count % 30 == 0:
                progress = int((frame_count / total_frames) * 100)
                jobs[job_id]['progress'] = progress
                print(f"[{job_id}] Progress: {progress}%")

        cap.release()
        out.release()
        
        # --- FALLBACK LOGIC FOR SHORT VIDEOS ---
        if not detected_accidents and best_fallback_data:
             print(f"[{job_id}] ⚠️ No long incident. Using Fallback (Conf: {best_fallback_conf:.2f})")
             fb_label, fb_before, fb_during = best_fallback_data
             
             # Save Fallback Images
             f_before_path = os.path.join(DATA_DIR, f"{job_id}_fb_before.jpg")
             cv2.imwrite(f_before_path, fb_before)
             
             f_during_path = os.path.join(DATA_DIR, f"{job_id}_fb_during.jpg")
             cv2.imwrite(f_during_path, fb_during)
             
             # Use last known frame as after
             f_after_path = os.path.join(DATA_DIR, f"{job_id}_fb_after.jpg")
             last_fr = frame_buffer[-1] if frame_buffer else fb_during
             cv2.imwrite(f_after_path, last_fr)
             
             fb_snapshots = [f_before_path, f_during_path, f_after_path]
             all_snapshot_paths.extend(fb_snapshots)
             
             all_reports = [] # Use the global one if needed, but safe to just append if it exists
             if auto_report:
                  report_result = report_to_backend(fb_snapshots, fb_label, output_path)
                  if report_result: all_reports.append(report_result)
                  
             detected_accidents.append({
                 "timestamp": 0, "label": fb_label, "snapshots": fb_snapshots
             })
        
        # Save Metadata
        metadata = {
            "has_accident": len(detected_accidents) > 0, 
            "snapshot_paths": all_snapshot_paths, # Send ALL snapshots
            "detected_accidents": detected_accidents,
            "incidents": incidents,
            # NEW: Single top-level report (using the first one if multiple)
            "aiReport": all_reports[0]['aiReport'] if all_reports else None,
            "incidentId": all_reports[0]['id'] if all_reports else None
        }
        json_path = output_path + ".json" 
        with open(json_path, 'w') as f:
            json.dump(metadata, f, indent=4)

        jobs[job_id]['status'] = 'COMPLETED'
        jobs[job_id]['progress'] = 100
        print(f"[{job_id}] Finished.")

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
            result = response.json()
            print("✅ Successfully reported to Backend. ID:", result.get('id'))
            return result
        else:
            print(f"❌ Backend Report Failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Error reporting to backend: {str(e)}")
        return None


# --- GLOBAL ASYNC LOOP SETUP (WEBRTC) ---
loop = asyncio.new_event_loop()

def start_loop():
    asyncio.set_event_loop(loop)
    loop.run_forever()

t = threading.Thread(target=start_loop, daemon=True)
t.start()
# -------------------------------

# -------------------------------

class YoloVideoTrack(VideoStreamTrack):
    def __init__(self, job_id, video_path, auto_report=False):
        super().__init__()
        self.job_id = job_id
        self.auto_report = auto_report # Store flag
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
             logger.error(f"Cannot open video: {video_path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.model = get_model("medium") # Default to medium for stream
        self.frame_count = 0
        self.skip_frames = 5 # Aggressive skip for CPU
        self.last_boxes = []
        
        # Detection Config
        self.CONF_THRESHOLD = 0.7
        self.TARGET_LABELS = ['accident', 'vehicle accident']
        
        # Accident Logic
        self.BUFFER_SIZE = int(self.fps * 4.0) # 4s Before
        self.frame_buffer = deque(maxlen=self.BUFFER_SIZE)
        self.snapshot_state = 'SEARCHING'
        self.frames_since_incident = 0
        self.current_accident_streak = 0
        self.CONFIRMATION_FRAMES = int(self.fps * 0.5)
        self.snapshot_paths = []
        self.current_incident_info = None
        
        # Accumulators for Frontend
        self.detected_accidents = []
        self.all_snapshot_paths = []
        self.all_snapshot_urls = [] # Web-accessible URLs
        
        # Data Dir
        # Use Global Temp Root to avoid Live Server hot-reload
        self.DATA_DIR = STREAM_DATA_ROOT
        self._stopped = False  # Flag to signal recv() to stop
        # self.DATA_DIR = os.path.join(os.getcwd(), 'data')
        # os.makedirs(self.DATA_DIR, exist_ok=True)


    async def recv(self):
        # Check if stream was stopped
        if self._stopped:
            return None
        
        pts, time_base = await self.next_timestamp()
        ret, frame = self.cap.read()
        if not ret:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()
            if not ret: return
        
        # --- OPTIMIZATION: RESIZE FRAME ---
        # Reduce resolution for stream performance (e.g. max width 640)
        h, w = frame.shape[:2]
        if w > 640:
            scale = 640 / w
            new_w, new_h = 640, int(h * scale)
            frame = cv2.resize(frame, (new_w, new_h))
        
        self.frame_count += 1
        self.frame_buffer.append(frame.copy())
        
        detection_found = False
        current_data = None
        
        # Optimization: Skip frames
        if self.frame_count % self.skip_frames == 0:
            results = self.model.track(frame, persist=True, imgsz=640, verbose=False, tracker="bytetrack.yaml")
            self.last_boxes = []
            if results:
                for result in results:
                    for box in result.boxes:
                        coords = tuple(map(int, box.xyxy[0]))
                        conf = float(box.conf[0])
                        cls_id = int(box.cls[0])
                        label = self.model.names[cls_id]
                        self.last_boxes.append((coords, label, conf))
                        
                        if label.lower() in self.TARGET_LABELS and conf > self.CONF_THRESHOLD:
                             detection_found = True
                             current_data = (label, conf)
        else:
            # Check cached boxes for detection
             for box_data in self.last_boxes:
                (coords, label, conf) = box_data
                if label.lower() in self.TARGET_LABELS and conf > self.CONF_THRESHOLD:
                      detection_found = True
                      current_data = (label, conf)
        
        # --- LOGIC DETECTION ---
        if detection_found:
             self.current_accident_streak += 1
             if self.snapshot_state == 'SEARCHING':
                  if self.current_accident_streak >= self.CONFIRMATION_FRAMES:
                       print(f"[Stream {self.job_id}] 🚨 Accident CONFIRMED!")
                       label, conf = current_data
                       
                       # Cache Info
                       self.current_incident_info = {"label": label, "time": self.frame_count/self.fps}
                       
                       # 1. Save BEFORE
                       before_frame = self.frame_buffer[0].copy() if self.frame_buffer else frame.copy()
                       add_timestamp(before_frame, (self.frame_count - len(self.frame_buffer)) / self.fps if self.frame_buffer else self.frame_count/self.fps)
                       before_path = os.path.join(self.DATA_DIR, f"{self.job_id}_{self.frame_count}_before.jpg")
                       cv2.imwrite(before_path, before_frame)
                       self.snapshot_paths = [before_path]
                       self.all_snapshot_paths.append(before_path)
                       self.all_snapshot_urls.append(f"/data/{os.path.basename(before_path)}")
                       
                       # 2. Save DURING (REWIND LOGIC)
                       # Instead of current frame, go back 0.5s to capture impact
                       SECONDS_TO_REWIND = 0.5 # Updated to match user preference 
                       frames_back = int(self.fps * SECONDS_TO_REWIND)
                       if len(self.frame_buffer) > frames_back:
                            during_frame = self.frame_buffer[-frames_back].copy()
                       elif self.frame_buffer:
                             during_frame = self.frame_buffer[0].copy()
                       else:
                             during_frame = frame.copy()

                       add_timestamp(during_frame, self.frame_count / self.fps)
                       during_path = os.path.join(self.DATA_DIR, f"{self.job_id}_{self.frame_count}_during.jpg")
                       cv2.imwrite(during_path, during_frame)
                       self.snapshot_paths.append(during_path)
                       self.all_snapshot_paths.append(during_path)
                       self.all_snapshot_urls.append(f"/data/{os.path.basename(during_path)}")
                       
                       self.snapshot_state = 'CAPTURING_AFTER'
                       self.frames_since_incident = 0
                       
                       # Update Global Job Status for Frontend
                       if self.job_id in jobs:
                            jobs[self.job_id]['status'] = 'DETECTED' 
                            # jobs[self.job_id].setdefault('incidents', []).append(self.current_incident_info)
                            # We update via 'detected_accidents' in AFTER block to be complete.

        else:
             self.current_accident_streak = 0
             
        # --- LOGIC AFTER ---
        if self.snapshot_state == 'CAPTURING_AFTER':
             self.frames_since_incident += 1
             if self.frames_since_incident >= (self.fps * 5.0): # 5s After
                  # 3. Save AFTER
                  after_frame = frame.copy()
                  add_timestamp(after_frame, self.frame_count / self.fps)
                  after_path = os.path.join(self.DATA_DIR, f"{self.job_id}_{self.frame_count}_after.jpg")
                  cv2.imwrite(after_path, after_frame)
                  self.snapshot_paths.append(after_path)
                  self.all_snapshot_paths.append(after_path)
                  self.all_snapshot_urls.append(f"/data/{os.path.basename(after_path)}")
                  
                  # Log incident
                  self.detected_accidents.append({
                        "timestamp": self.current_incident_info['time'],
                        "label": self.current_incident_info['label'],
                        "snapshots": list(self.snapshot_paths)
                  })

                  # Report / Update
                  if self.auto_report:
                       print(f"[Stream {self.job_id}] Snapshot complete. Reporting...")
                  
                  # Update Global Metadata for Frontend Polling
                  if self.job_id in jobs:
                       jobs[self.job_id]['snapshot_paths'] = list(self.all_snapshot_paths) # ALL images
                       jobs[self.job_id]['snapshot_urls'] = list(self.all_snapshot_urls) # URLs for Frontend
                       jobs[self.job_id]['detected_accidents'] = self.detected_accidents # Structured Data
                       jobs[self.job_id]['has_accident'] = True
                  
                  # Conditional Auto Report
                  if self.auto_report:
                       report_result = report_to_backend(self.snapshot_paths, self.current_incident_info['label'])
                       if report_result and self.job_id in jobs:
                           # UPDATE GLOBAL JOB STATUS WITH AI REPORT
                           jobs[self.job_id]['aiReport'] = report_result.get('aiReport')
                           jobs[self.job_id]['incidentId'] = report_result.get('id')
                           print(f"[Stream {self.job_id}] AI Report Captured (ID: {report_result.get('id')})")
                  else:
                       print(f"[Stream {self.job_id}] Auto-report disabled. Skipping.")
                  
                  self.snapshot_state = 'COOLDOWN'
                  self.frames_since_incident = 0

        if self.snapshot_state == 'COOLDOWN':
             self.frames_since_incident += 1
             if self.frames_since_incident >= (self.fps * 5.0):
                  self.snapshot_state = 'SEARCHING'

        # Draw cached boxes
        annotated_frame = frame.copy()
        add_timestamp(annotated_frame, self.frame_count / self.fps)
        
        # Visual Debug Bar
        if self.current_accident_streak > 0 and self.snapshot_state == 'SEARCHING':
             bar_width = min(int((self.current_accident_streak / self.CONFIRMATION_FRAMES) * 200), 200)
             cv2.rectangle(annotated_frame, (50, 50), (50 + bar_width, 70), (0, 0, 255), -1)
             cv2.putText(annotated_frame, "CONFIRMING...", (50, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        for box_data in self.last_boxes:
            (coords, label, conf) = box_data
            x1, y1, x2, y2 = coords
            # Filter labels if needed, or use all
            color = (0, 0, 255) if "accident" in label.lower() else (0, 255, 0)
            draw_styled_box(annotated_frame, x1, y1, x2, y2, label, conf, color)
        frame_rgb = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
        
        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

    def stop(self):
        self._stopped = True  # Signal recv() to stop
        print(f"[Stream {self.job_id}] Stop signal received.")
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
        
    if not auto_report:
        print(f"⚠️ WARNING: Auto-Report is DISABLED by request. 'Create AI Report' button will appear manually.")
    else:
        print(f"✅ Auto-Report is ENABLED.")
    
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
            "modelType": model_type,
            "autoReport": auto_report # Store flag
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
        if pc.connectionState in ["failed", "closed", "disconnected"]:
            print("Client disconnected, cleaning up...")
            await pc.close()
            pcs.discard(pc)
            
            # Explicitly stop tracks and update job status
            for sender in pc.getSenders():
                if sender.track:
                    sender.track.stop()
            
            if job_id in jobs:
                jobs[job_id]['status'] = 'STOPPED'
                print(f"Job {job_id} stopped.")

    if os.path.exists(job["inputPath"]):
        # Pass auto_report from job config
        video_track = YoloVideoTrack(job_id, job["inputPath"], job.get("autoReport", False))
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

@app.route('/data/<path:filename>')
def serve_data(filename):
    return send_from_directory(STREAM_DATA_ROOT, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
