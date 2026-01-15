import cv2
import time
import os
from collections import deque
from PyQt6.QtCore import QThread, pyqtSignal
from ultralytics import YOLO
import numpy as np

# Root dir setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

class DetectionThread(QThread):
    change_pixmap_signal = pyqtSignal(np.ndarray)
    detection_signal = pyqtSignal(str, str)
    snapshot_saved = pyqtSignal(str, str, str)  # Signal emit 3 paths
    process_finished_signal = pyqtSignal(dict) # NEW: Signal for analyst completion
    progress_signal = pyqtSignal(int) # NEW: Progress percentage

    def __init__(self, model_path='best.pt', source=0, save_path=None, custom_labels="accident, vehicle accident", conf_threshold=0.70):
        super().__init__()
        self.model_path = model_path
        self.source = source
        self.save_path = save_path
        self.custom_labels = custom_labels
        self.conf_threshold = conf_threshold
        self.model = None
        self.running = True
        self.paused = False
        self.out = None

    def pause(self):
        """Pause/Resume toggle"""
        self.paused = not self.paused
        return self.paused

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

        # --- DYNAMIC TIME CONFIG ---
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) # Get total frames
        if video_fps == 0 or np.isnan(video_fps): 
            video_fps = 30 # Fallback
        
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Setup Video Writer
        if self.save_path:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.out = cv2.VideoWriter(self.save_path, fourcc, video_fps, (width, height))
        
        # Config
        BEFORE_SECONDS = 3.0
        AFTER_SECONDS = 3.5 
        
        # Buffer calc
        BUFFER_SIZE = int(video_fps * BEFORE_SECONDS)
        AFTER_FRAMES_REQUIRED = int(video_fps * AFTER_SECONDS)
        
        SKIP_FRAMES = 3 # Optimize performance
        
        frame_buffer = deque(maxlen=BUFFER_SIZE)
        
        # State vars
        snapshot_state = "IDLE" 
        frames_since_incident = 0
        current_incident_label = ""
        current_sequence_id = 0
        last_alert_time = 0
        alert_cooldown = 30 # seconds
        
        frame_count = 0
        last_valid_frame = None 
        last_boxes = []
        
        # Track last incident for final report
        final_snapshots = []
        final_incident_id = None

        print(f"Video Info: FPS={video_fps}, Buffer Size={BUFFER_SIZE}, After Frames={AFTER_FRAMES_REQUIRED}")

        # 3. MAIN LOOP
        self.running = True
        while self.running and cap.isOpened():
            # --- PAUSE LOGIC ---
            if self.paused:
                time.sleep(0.1) # Sleep to save CPU
                continue
                
            ret, frame = cap.read()
            
            # --- END OF VIDEO CHECK ---
            if not ret:
                print("End of video stream.")
                if snapshot_state == "WAITING_FOR_AFTER" and last_valid_frame is not None:
                    print("Video ended early. Forcing capture of AFTER image.")
                    path_after = self.save_image(last_valid_frame, current_sequence_id, current_incident_label, "3_after")
                    if 'current_snapshot_paths' in locals():
                        current_snapshot_paths[2] = path_after
                        self.snapshot_saved.emit(*current_snapshot_paths)
                break

            last_valid_frame = frame.copy()
            frame_buffer.append(frame.copy())
            frame_count += 1
            annotated_frame = frame.copy()
            
            # Emit Progress
            if total_frames > 0:
                progress = int((frame_count / total_frames) * 100)
                self.progress_signal.emit(progress)

            # --- A. DETECTION ---
            if frame_count % SKIP_FRAMES == 0:
                results = self.model.track(frame, persist=True, verbose=False, conf=self.conf_threshold)
                
                last_boxes = [] 
                
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
                    final_incident_id = current_sequence_id # New: Track ID
                    
                    print(f"!!! Incident Detected: {detected_label}")

                    # 1. Save BEFORE
                    frame_before = frame_buffer[0] if frame_buffer else frame
                    path_before = self.save_image(frame_before, current_sequence_id, detected_label, "1_before")
                    
                    # 2. Save DURING
                    path_during = self.save_image(frame, current_sequence_id, detected_label, "2_during")
                    
                    current_snapshot_paths = [path_before, path_during, None]
                    
                    # Emit signal
                    self.detection_signal.emit(detected_label, path_during)

            # --- B. DRAW BOXES ---
            for (x1, y1, x2, y2, label, conf) in last_boxes:
                color = (0, 0, 255) if label.lower() in target_labels else (0, 255, 0)
                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(annotated_frame, f"{label} {conf:.2f}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            # --- C. STATE MACHINE UPDATE ---
            if snapshot_state == "WAITING_FOR_AFTER":
                frames_since_incident += 1
                if frames_since_incident >= AFTER_FRAMES_REQUIRED:
                    # 3. Save AFTER
                    path_after = self.save_image(frame, current_sequence_id, current_incident_label, "3_after")
                    print("Sequence capture complete.")
                    
                    if 'current_snapshot_paths' in locals():
                        current_snapshot_paths[2] = path_after
                        self.snapshot_saved.emit(*current_snapshot_paths)
                        final_snapshots = current_snapshot_paths # New: Store for final emit

                    snapshot_state = "IDLE"

            # --- D. OUTPUT ---
            self.change_pixmap_signal.emit(annotated_frame)
            if self.out:
                self.out.write(annotated_frame)

        # Cleanup
        print("Stopping detection thread...")
        cap.release()
        if self.out:
            self.out.release()
        
        # NEW: Emit completion signal
        self.process_finished_signal.emit({
            'success': True,
            'output_path': self.save_path,
            'snapshots': final_snapshots,
            'incident_id': str(final_incident_id) if final_incident_id else str(int(time.time()))
        })
            
    def stop(self):
        """Signal thread to stop and wait"""
        self.running = False
        self.wait()

    def save_image(self, frame, seq_id, label, suffix):
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        
        filename = f"{seq_id}_{label}_{suffix}.jpg"
        filepath = os.path.join(DATA_DIR, filename)
        cv2.imwrite(filepath, frame)
        return filepath