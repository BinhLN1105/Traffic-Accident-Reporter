import cv2
import time
import os
from collections import deque
from PyQt6.QtCore import QThread, pyqtSignal
from ultralytics import YOLO
import numpy as np

# Giữ nguyên phần tạo thư mục
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

class DetectionThread(QThread):
    change_pixmap_signal = pyqtSignal(np.ndarray)
    detection_signal = pyqtSignal(str, str)

    def __init__(self, model_path='best.pt', source=0, save_path=None, custom_labels="accident, vehicle accident", conf_threshold=0.70):
        super().__init__()
        self.model_path = model_path
        self.source = source
        self.save_path = save_path
        self.custom_labels = custom_labels
        self.conf_threshold = conf_threshold
        self.running = True
        self.model = None
        self.out = None

    def run(self):
        target_labels = [l.strip().lower() for l in self.custom_labels.split(',') if l.strip()]
        
        # 1. Load Model
        try:
            print(f"Loading model from {self.model_path}...")
            self.model = YOLO(self.model_path)
        except Exception as e:
            print(f"Error loading model: {e}")
            return

        # 2. Open Video Source
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            print("Cannot open video source")
            return

        # --- CẤU HÌNH THỜI GIAN ĐỘNG ---
        # Lấy FPS thực tế của video (quan trọng cho video file)
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        if video_fps == 0 or np.isnan(video_fps): 
            video_fps = 30 # Fallback nếu là webcam
        
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Setup Video Writer
        if self.save_path:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.out = cv2.VideoWriter(self.save_path, fourcc, video_fps, (width, height))
        
        # Cấu hình thời gian
        BEFORE_SECONDS = 3.0
        AFTER_SECONDS = 3.5 # Có thể tăng lên 3.0 hoặc 4.0 nếu tai nạn kéo dài
        
        # Tính toán số frame cần buffer dựa trên FPS thực
        BUFFER_SIZE = int(video_fps * BEFORE_SECONDS)
        AFTER_FRAMES_REQUIRED = int(video_fps * AFTER_SECONDS)
        
        SKIP_FRAMES = 3 # Skip để tối ưu performance
        
        frame_buffer = deque(maxlen=BUFFER_SIZE)
        
        # Các biến trạng thái
        snapshot_state = "IDLE" 
        frames_since_incident = 0
        current_incident_label = ""
        current_sequence_id = 0
        last_alert_time = 0
        alert_cooldown = 30 # Giây
        
        frame_count = 0
        last_valid_frame = None # Lưu frame cuối cùng hợp lệ để xử lý khi video hết
        last_boxes = []

        print(f"Video Info: FPS={video_fps}, Buffer Size={BUFFER_SIZE}, After Frames={AFTER_FRAMES_REQUIRED}")

        while self.running:
            ret, frame = cap.read()
            
            # --- XỬ LÝ KHI VIDEO KẾT THÚC (QUAN TRỌNG CHO CASE 1) ---
            if not ret:
                print("End of video stream.")
                # Nếu đang đợi chụp ảnh After mà video hết -> Chụp ngay frame cuối cùng
                if snapshot_state == "WAITING_FOR_AFTER" and last_valid_frame is not None:
                    print("Video ended early. Forcing capture of AFTER image.")
                    self.save_image(last_valid_frame, current_sequence_id, current_incident_label, "3_after")
                break

            last_valid_frame = frame.copy()
            frame_buffer.append(frame.copy())
            frame_count += 1
            annotated_frame = frame.copy()

            # --- A. PHẦN NHẬN DIỆN ---
            if frame_count % SKIP_FRAMES == 0:
                results = self.model.track(frame, persist=True, verbose=False, conf=self.conf_threshold)
                
                last_boxes = [] # Reset boxes cũ
                
                current_time = time.time()
                is_incident_now = False
                detected_label = ""

                for result in results:
                    for box in result.boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        cls_id = int(box.cls[0])
                        label = self.model.names[cls_id]
                        conf = float(box.conf[0])
                        
                        last_boxes.append((x1, y1, x2, y2, label, conf))

                        # Logic trigger
                        if snapshot_state == "IDLE" and (current_time - last_alert_time > alert_cooldown):
                            if label.lower() in target_labels:
                                is_incident_now = True
                                detected_label = label

                # --- TRIGGER EVENT ---
                if is_incident_now:
                    snapshot_state = "WAITING_FOR_AFTER"
                    frames_since_incident = 0
                    current_incident_label = detected_label
                    last_alert_time = current_time
                    current_sequence_id = int(time.time())
                    
                    print(f"!!! Incident Detected: {detected_label}")

                    # 1. Save BEFORE (Lấy frame cũ nhất trong buffer)
                    # Nếu buffer chưa đầy (đầu video), lấy frame đầu tiên có được
                    frame_before = frame_buffer[0] if frame_buffer else frame
                    self.save_image(frame_before, current_sequence_id, detected_label, "1_before")
                    
                    # 2. Save DURING
                    self.save_image(frame, current_sequence_id, detected_label, "2_during")
                    
                    # Gửi signal UI
                    path_during = os.path.join(DATA_DIR, f"{current_sequence_id}_{detected_label}_2_during.jpg")
                    self.detection_signal.emit(detected_label, path_during)

            # --- B. VẼ LẠI BOX ---
            for (x1, y1, x2, y2, label, conf) in last_boxes:
                color = (0, 0, 255) if label.lower() in target_labels else (0, 255, 0)
                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(annotated_frame, f"{label} {conf:.2f}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            # --- C. STATE MACHINE UPDATE ---
            if snapshot_state == "WAITING_FOR_AFTER":
                frames_since_incident += 1
                # Kiểm tra đủ thời gian chưa
                if frames_since_incident >= AFTER_FRAMES_REQUIRED:
                    # 3. Save AFTER
                    self.save_image(frame, current_sequence_id, current_incident_label, "3_after")
                    print("Sequence capture complete.")
                    snapshot_state = "IDLE"

            # --- D. OUTPUT ---
            self.change_pixmap_signal.emit(annotated_frame)
            if self.out:
                self.out.write(annotated_frame)

        # Cleanup
        cap.release()
        if self.out:
            self.out.release()
            
    def save_image(self, frame, seq_id, label, suffix):
        """Hàm hỗ trợ lưu ảnh để code gọn hơn"""
        filename = f"{seq_id}_{label}_{suffix}.jpg"
        path = os.path.join(DATA_DIR, filename)
        cv2.imwrite(path, frame)

    def stop(self):
        self.running = False
        self.wait()