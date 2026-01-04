import cv2
import time
import os
from collections import deque
from PyQt6.QtCore import QThread, pyqtSignal
from ultralytics import YOLO
import numpy as np

# Tạo thư mục data nếu chưa có
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

class DetectionThread(QThread):
    change_pixmap_signal = pyqtSignal(np.ndarray)
    detection_signal = pyqtSignal(str, str) # incident_type, image_path

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
        
        # Setup Video Writer
        if self.save_path and cap.isOpened():
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            # Resize output nếu cần để giảm dung lượng
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.out = cv2.VideoWriter(self.save_path, fourcc, fps, (width, height))
        
        # --- LOGIC CONFIG ---
        last_alert_time = 0
        alert_cooldown = 30 
        
        FPS = 30
        # 2 giây trước tai nạn
        BEFORE_SECONDS = 2.0
        # 2.5 giây sau tai nạn
        AFTER_SECONDS = 2.5
        
        BUFFER_SIZE = FPS * BEFORE_SECONDS
        AFTER_FRAMES = FPS * AFTER_SECONDS
        
        # Frame Skipping Config
        SKIP_FRAMES = 3 
        frame_count = 0

        frame_buffer = deque(maxlen=BUFFER_SIZE)
        snapshot_state = "IDLE"
        frames_since_incident = 0
        current_incident_label = ""
        current_sequence_id = 0
        
        # Lưu trữ kết quả cũ để vẽ lên frame bị skip (tránh nhấp nháy)
        last_boxes = [] 

        while self.running:
            ret, frame = cap.read()
            if not ret: break

            # Luôn thêm frame vào buffer (quan trọng cho ảnh Before)
            frame_buffer.append(frame.copy())
            frame_count += 1
            
            # Mặc định hình hiển thị là frame gốc
            annotated_frame = frame.copy() 

            # --- A. PHẦN NHẬN DIỆN (Chỉ chạy mỗi 3 frame) ---
            if frame_count % SKIP_FRAMES == 0:
                # Dùng track để ổn định ID
                results = self.model.track(frame, persist=True, verbose=False, conf=self.conf_threshold)
                
                # Cập nhật danh sách box mới nhất
                last_boxes = []
                
                # Kiểm tra detection
                current_time = time.time()
                is_incident = False
                detected_label = ""
                
                for result in results:
                    for box in result.boxes:
                        # Lưu thông tin box để vẽ
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        cls_id = int(box.cls[0])
                        label = self.model.names[cls_id]
                        conf = float(box.conf[0])
                        
                        # Lưu vào list để vẽ lại ở các frame sau
                        last_boxes.append((x1, y1, x2, y2, label, conf))

                        # Logic phát hiện tai nạn
                        if snapshot_state == "IDLE" and (current_time - last_alert_time > alert_cooldown):
                            if label.lower() in target_labels:
                                is_incident = True
                                detected_label = label

                # --- STATE MACHINE (Xử lý sự kiện tai nạn) ---
                if is_incident:
                    snapshot_state = "WAITING_FOR_AFTER"
                    frames_since_incident = 0
                    current_incident_label = detected_label
                    last_alert_time = current_time
                    current_sequence_id = int(time.time())
                    
                    print(f"!!! Incident Detected: {detected_label}")

                    # 1. Save BEFORE (Lấy frame cũ nhất trong buffer)
                    if len(frame_buffer) > 0:
                        path_before = os.path.join(DATA_DIR, f"{current_sequence_id}_{detected_label}_1_before.jpg")
                        cv2.imwrite(path_before, frame_buffer[0])
                    
                    # 2. Save DURING (Frame hiện tại)
                    path_during = os.path.join(DATA_DIR, f"{current_sequence_id}_{detected_label}_2_during.jpg")
                    cv2.imwrite(path_during, frame)
                    
                    # Gửi signal báo UI
                    self.detection_signal.emit(detected_label, path_during)

            # --- B. PHẦN VẼ LẠI (Chạy MỌI frame để chống nhấp nháy) ---
            # Vẽ lại các box từ lần nhận diện gần nhất lên frame hiện tại
            for (x1, y1, x2, y2, label, conf) in last_boxes:
                # Chọn màu (đỏ cho tai nạn, xanh cho xe thường)
                color = (0, 0, 255) if label.lower() in target_labels else (0, 255, 0)
                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(annotated_frame, f"{label} {conf:.2f}", (x1, y1 - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            # --- C. STATE MACHINE UPDATE (Chạy MỌI frame) ---
            # Sửa lỗi logic: Đếm frame phải nằm ngoài khối if frame_count % SKIP
            if snapshot_state == "WAITING_FOR_AFTER":
                frames_since_incident += 1
                if frames_since_incident >= AFTER_FRAMES:
                    # 3. Save AFTER
                    path_after = os.path.join(DATA_DIR, f"{current_sequence_id}_{current_incident_label}_3_after.jpg")
                    cv2.imwrite(path_after, frame)
                    print("Sequence capture complete.")
                    snapshot_state = "IDLE"

            # --- D. OUTPUT ---
            # Gửi hình đã vẽ box ra UI
            self.change_pixmap_signal.emit(annotated_frame)
            
            # Ghi vào file video (nếu có)
            if self.out:
                self.out.write(annotated_frame)

        # Cleanup
        cap.release()
        if self.out:
            self.out.release()

    def stop(self):
        self.running = False
        self.wait()