import cv2
import time
import os
from collections import deque
from PyQt6.QtCore import QThread, pyqtSignal
from ultralytics import YOLO
import numpy as np

# DATA_DIR = "d:/ProjectHTGTTM_CarTrafficReport/data" (Dynamic approach below)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

class DetectionThread(QThread):
    change_pixmap_signal = pyqtSignal(np.ndarray)
    detection_signal = pyqtSignal(str, str) # incident_type, image_path

    def __init__(self, model_path='best.pt', source=0, save_path=None):
        super().__init__()
        self.model_path = model_path
        self.source = source
        self.save_path = save_path
        self.running = True
        self.model = None
        self.out = None

    def run(self):
        # Load Model
        try:
            print(f"Loading model from {self.model_path}...")
            self.model = YOLO(self.model_path)
        except Exception as e:
            print(f"Error loading model: {e}")
            return

        # Open Source
        cap = cv2.VideoCapture(self.source)
        
        # Setup Video Writer if save_path is provided
        if self.save_path and cap.isOpened():
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.out = cv2.VideoWriter(self.save_path, fourcc, fps, (width, height))
        
        last_alert_time = 0
        alert_cooldown = 30 # Increase cooldown to avoid overlapping sequences
        
        # Snapshot Logic
        frame_buffer = deque(maxlen=40) # Store ~1-2 seconds of video (at 30fps)
        snapshot_state = "IDLE" # IDLE, WAITING_FOR_AFTER
        frames_since_incident = 0
        TRIGGER_AFTER_FRAMES = 45 # ~1.5 seconds after
        current_incident_label = ""
        
        while self.running:
            ret, frame = cap.read()
            if not ret:
                break

            # YOLO Inference
            results = self.model(frame, verbose=False)
            annotated_frame = results[0].plot()

            # Maintain buffer
            frame_buffer.append(frame.copy())

            # Check for detections
            current_time = time.time()
            is_incident = False
            detected_label = ""
            
            # Logic: Only check if IDLE or cooldown passed (to avoid spamming)
            if snapshot_state == "IDLE" and (current_time - last_alert_time > alert_cooldown):
                for result in results:
                    for box in result.boxes:
                        class_id = int(box.cls[0])
                        label = self.model.names[class_id]
                        conf = float(box.conf[0])
                        
                        # Check logic
                        if conf > 0.6 and ("accident" in label.lower() or "crash" in label.lower() or "collision" in label.lower()): 
                             is_incident = True
                             detected_label = label
                             print(f"Detected {label} ({conf:.2f})")
                             break
            
            # STATE MACHINE for Snapshots
            if is_incident and snapshot_state == "IDLE":
                snapshot_state = "WAITING_FOR_AFTER"
                frames_since_incident = 0
                current_incident_label = detected_label
                last_alert_time = current_time
                
                # Use a consistent ID for the whole sequence
                sequence_id = int(time.time())
                self.current_sequence_id = sequence_id 
                
                # 1. Save BEFORE (Oldest in buffer)
                if len(frame_buffer) > 0:
                    path_before = os.path.join(DATA_DIR, f"{sequence_id}_{detected_label}_1_before.jpg")
                    cv2.imwrite(path_before, frame_buffer[0])
                
                # 2. Save DURING (Current)
                path_during = os.path.join(DATA_DIR, f"{sequence_id}_{detected_label}_2_during.jpg")
                cv2.imwrite(path_during, frame)
                
                # Emit Signal for API (Send the 'During' image)
                self.detection_signal.emit(detected_label, path_during)
                
            elif snapshot_state == "WAITING_FOR_AFTER":
                frames_since_incident += 1
                if frames_since_incident >= TRIGGER_AFTER_FRAMES:
                    # 3. Save AFTER using same sequence_id
                    path_after = os.path.join(DATA_DIR, f"{self.current_sequence_id}_{current_incident_label}_3_after.jpg")
                    cv2.imwrite(path_after, frame)
                    print("Sequence capture complete.")
                    snapshot_state = "IDLE"

            # Update UI
            self.change_pixmap_signal.emit(annotated_frame)
            
            # Save Frame
            if self.out:
                self.out.write(annotated_frame)

        cap.release()
        if self.out:
            self.out.release()

    def stop(self):
        self.running = False
        self.wait()
