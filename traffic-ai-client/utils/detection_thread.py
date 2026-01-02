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
        # Parse labels
        target_labels = [l.strip().lower() for l in self.custom_labels.split(',') if l.strip()]
        print(f"Tracking labels: {target_labels} | Conf: {self.conf_threshold}")
        
        # ... [Load Model & Video] ...

        # Load Model
        try:
            print(f"Loading model from {self.model_path}...")
            self.model = YOLO(self.model_path)
            # ... 
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
        alert_cooldown = 30 
        
        # Snapshot Logic ...
        FPS = 30
        BEFORE_SECONDS = 3
        AFTER_SECONDS = 3
        BUFFER_SIZE = FPS * BEFORE_SECONDS
        AFTER_FRAMES = FPS * AFTER_SECONDS
        
        # Frame Skipping Config
        SKIP_FRAMES = 3 
        frame_count = 0

        frame_buffer = deque(maxlen=BUFFER_SIZE)
        snapshot_state = "IDLE"
        frames_since_incident = 0
        current_incident_label = ""
        
        while self.running:
            ret, frame = cap.read()
            if not ret: break

            # Appending to buffer MUST happen every frame to ensure valid history
            frame_buffer.append(frame.copy())

            frame_count += 1
            annotated_frame = frame
            
            # --- Frame Skipping for Inference ---
            if frame_count % SKIP_FRAMES == 0:
                # YOLO Inference
                results = self.model(frame, verbose=False)
                annotated_frame = results[0].plot()

                # Check for detections
                current_time = time.time()
                is_incident = False
                detected_label = ""
                
                if snapshot_state == "IDLE" and (current_time - last_alert_time > alert_cooldown):
                    for result in results:
                         for box in result.boxes:
                            class_id = int(box.cls[0])
                            label = self.model.names[class_id]
                            conf = float(box.conf[0])
                            
                            # Use Custom Labels & Confidence Threshold
                            if conf >= self.conf_threshold and label.lower() in target_labels: 
                                 is_incident = True
                                 detected_label = label
                                 break
                
                # STATE MACHINE updates
                if is_incident and snapshot_state == "IDLE":
                    snapshot_state = "WAITING_FOR_AFTER"
                    frames_since_incident = 0
                    current_incident_label = detected_label
                    last_alert_time = current_time
                    
                    sequence_id = int(time.time())
                    self.current_sequence_id = sequence_id 
                    
                    # 1. Save BEFORE (Oldest in buffer)
                    if len(frame_buffer) > 0:
                        path_before = os.path.join(DATA_DIR, f"{sequence_id}_{detected_label}_1_before.jpg")
                        cv2.imwrite(path_before, frame_buffer[0])
                    
                    # 2. Save DURING (Current)
                    path_during = os.path.join(DATA_DIR, f"{sequence_id}_{detected_label}_2_during.jpg")
                    cv2.imwrite(path_during, frame)
                    
                    self.detection_signal.emit(detected_label, path_during)
                
            elif snapshot_state == "WAITING_FOR_AFTER":
                frames_since_incident += 1
                if frames_since_incident >= AFTER_FRAMES:
                    # 3. Save AFTER
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
