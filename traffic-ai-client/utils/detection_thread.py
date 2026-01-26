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

    def __init__(self, model_path='best.pt', source=0, save_path=None, custom_labels="accident, vehicle accident", conf_threshold=0.70, loop=True):
        super().__init__()
        self.model_path = model_path
        self.source = source
        self.save_path = save_path
        self.custom_labels = custom_labels
        self.conf_threshold = conf_threshold
        self.loop = loop # Control looping behavior
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
        
        # --- Pre-calculate Resize Dimensions ---
        target_width = width
        target_height = height
        if width > 640:
            scale = 640 / width
            target_width = 640
            target_height = int(height * scale)
        # ---------------------------------------

        # Setup Video Writer
        if self.save_path:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.out = cv2.VideoWriter(self.save_path, fourcc, video_fps, (target_width, target_height))
        
        # Config matches server.py
        BEFORE_SECONDS = 4.0
        AFTER_SECONDS = 5.0 
        
        # Buffer calc
        BUFFER_SIZE = int(video_fps * BEFORE_SECONDS)
        AFTER_FRAMES_REQUIRED = int(video_fps * AFTER_SECONDS)
        
        SKIP_FRAMES = 3 # Process every 3rd frame (matches server)

        
        frame_buffer = deque(maxlen=BUFFER_SIZE)
        
        # State vars
        snapshot_state = "IDLE" 
        frames_since_incident = 0
        current_incident_label = ""
        current_sequence_id = 0
        last_alert_time = 0
        alert_cooldown = 30 # seconds
        current_accident_streak = 0 # Initialize streak counter
        
        # Fallback Tracking
        best_fallback_conf = 0.0
        best_fallback_data = None # (label, frame_before, frame_during)
        
        frame_count = 0
        last_boxes = []
        
        # Anti-Flicker Logic
        missing_frame_tolerance_count = 0
        MAX_MISSING_FRAMES = 5 # Allow 5 frames (approx 0.15s) of flicker
        
        # Incident Start Capture
        potential_incident_frame = None
        
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
                
            # --- LOOP LOGIC & FRAME READ ---
            ret, frame = cap.read()
            
            # Auto-loop if video ends AND loop mode is ON
            if not ret:
                if self.loop:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
                    if not ret: break 
                else:
                    # Non-loop mode: Just break
                    print("End of video stream (No Loop).")
                    break
            
            # --- OPTIMIZATION (Resize for Speed) ---
            # Resize large frames to max 640 width to improve FPS
            h, w = frame.shape[:2]
            if w > 640:
                scale = 640 / w
                new_w, new_h = 640, int(h * scale)
                frame = cv2.resize(frame, (new_w, new_h))

            last_valid_frame = frame.copy()
            frame_buffer.append(frame.copy())
            frame_count += 1
            annotated_frame = frame.copy()
            
            # Emit Progress (Looping makes this tricky, but we can wrap it)
            if total_frames > 0:
                # Wrap progress 0-100% per loop iteration
                current_loop_frame = frame_count % total_frames
                progress = int((current_loop_frame / total_frames) * 100)
                self.progress_signal.emit(progress)

            # --- A. DETECTION ---
            # Skip frames logic (Server uses % 3)
            if frame_count % 3 == 0:
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
                        
                        # Fix: Check valid label to trigger logic
                        if label.lower() in target_labels:
                            detected_label = label
                            
                            # Update Fallback Candidate (Best Confidence)
                            if conf > best_fallback_conf:
                                best_fallback_conf = conf
                                fb_before = frame_buffer[0].copy() if frame_buffer else frame.copy()
                                fb_during = frame.copy()
                                best_fallback_data = (label, fb_before, fb_during)

                # --- LOGIC CONFIRMATION (Persistence Check) ---
                ACCIDENT_DURATION_THRESHOLD = 0.5 # Cần 0.5s để xác thực
                CONFIRMATION_FRAMES = int(video_fps * ACCIDENT_DURATION_THRESHOLD)
                
                if detected_label:
                    current_accident_streak += 1
                    missing_frame_tolerance_count = 0 # Reset tolerance on hit
                    
                    # Capture exact moment incident STARTS (Streak == 1)
                    if current_accident_streak == 1:
                        # COMPENSATION FOR AI DELAY
                        # AI detects taking a few frames. User feels it's "late".
                        # We grab a frame from ~0.5s AGO (approx 15 frames) from buffer to get "Impact Moment".
                        rewind_frames = int(video_fps * 0.3) # 0.3s rewind
                        if len(frame_buffer) > rewind_frames:
                            potential_incident_frame = frame_buffer[-rewind_frames].copy()
                        elif frame_buffer:
                            potential_incident_frame = frame_buffer[0].copy()
                        else:
                            potential_incident_frame = frame.copy()
                        
                else:
                    # ANTI-FLICKER: Don't reset immediately
                    if current_accident_streak > 0 and missing_frame_tolerance_count < MAX_MISSING_FRAMES:
                        missing_frame_tolerance_count += 1
                        # Sustain streak (don't increment, don't reset)
                    else:
                        current_accident_streak = 0
                        potential_incident_frame = None
                        missing_frame_tolerance_count = 0

                # --- TRIGGER EVENT ---
                if snapshot_state == "IDLE" and \
                   (current_time - last_alert_time > alert_cooldown) and \
                   current_accident_streak >= CONFIRMATION_FRAMES:
                    
                    is_incident_now = True
                    
                    SECONDS_TO_REWIND = 1.0  
                    frames_back = int(video_fps * SECONDS_TO_REWIND)
                    
                    # Lấy frame từ buffer
                    if len(frame_buffer) > frames_back:
                        snap_frame = frame_buffer[-frames_back].copy() # Lấy ảnh cũ
                        print(f"📸 Captured frame from {SECONDS_TO_REWIND}s ago!")
                    elif frame_buffer:
                        snap_frame = frame_buffer[0].copy() # Lấy ảnh cũ nhất có thể
                    else:
                        snap_frame = frame.copy() # Bất đắc dĩ mới lấy ảnh hiện tại

                    # Các thiết lập biến trạng thái
                    last_alert_time = current_time
                    current_sequence_id = int(time.time())
                    final_incident_id = current_sequence_id
                    current_incident_label = detected_label
                    frames_since_incident = 0

                    # --- LƯU ẢNH ---
                    if self.loop:
                         # Chế độ Live: Lưu Before và During
                         # 1. Before: Lấy từ buffer
                         frame_before = frame_buffer[0] if frame_buffer else frame
                         path_before = self.save_image(frame_before, current_sequence_id, detected_label, "1_before")

                         # 2. During: Lưu ngay cái ảnh vừa "lôi từ quá khứ" về
                         path_during = self.save_image(snap_frame, current_sequence_id, detected_label, "2_during")
                        
                         current_snapshot_paths = [path_before, path_during, None]
                         final_snapshots = current_snapshot_paths
                        
                         self.snapshot_saved.emit(*current_snapshot_paths)
                        
                         snapshot_state = "WAITING_FOR_AFTER" 
                        
                    else:
                        # Chế độ Analyst
                        snapshot_state = "WAITING_FOR_AFTER"
                        
                        # 1. Before: Lấy ảnh cũ nhất trong buffer (cách đây 4s)
                        frame_before = frame_buffer[0] if frame_buffer else frame
                        path_before = self.save_image(frame_before, current_sequence_id, detected_label, "1_before")
                        
                        # 2. During: Lấy cái ảnh "Time Machine" mình vừa lôi ra
                        path_during = self.save_image(snap_frame, current_sequence_id, detected_label, "2_during")
                        
                        current_snapshot_paths = [path_before, path_during, None]
                        final_snapshots = current_snapshot_paths 
                        
                        self.detection_signal.emit(detected_label, path_during)

            # --- B. DRAW BOXES & TIMESTAMP ---
            # Add Timestamp (Server Style)
            time_str = str(time.strftime("%H:%M:%S", time.gmtime(frame_count / video_fps)))
            cv2.putText(annotated_frame, f"Time: {time_str}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
            cv2.putText(annotated_frame, f"Time: {time_str}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            for (x1, y1, x2, y2, label, conf) in last_boxes:
                color = (0, 0, 255) if label.lower() in target_labels else (0, 255, 0)
                # Styled Box
                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                
                # Label with background
                text = f"{label} {conf:.2f}"
                (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                cv2.rectangle(annotated_frame, (x1, y1 - 20), (x1 + w, y1), color, -1)
                cv2.putText(annotated_frame, text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            
            # --- DEBUG BAR ---
            if current_accident_streak > 0 and snapshot_state == "IDLE":
                bar_width = min(int((current_accident_streak / CONFIRMATION_FRAMES) * 100), 100)
                cv2.rectangle(annotated_frame, (10, 10), (10 + bar_width, 20), (0, 0, 255), -1)

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
                        final_snapshots = current_snapshot_paths 

                    snapshot_state = "IDLE"

            # --- D. OUTPUT ---
            # Emit simplified frame for UI
            self.change_pixmap_signal.emit(annotated_frame)
            if self.out:
                self.out.write(annotated_frame)

        # Cleanup
        print("Stopping detection thread...")
        cap.release()
        if self.out:
            self.out.release()
            
        # FORCE COMPLETE SNAPSHOT IF PENDING
        if snapshot_state == "WAITING_FOR_AFTER" and 'current_snapshot_paths' in locals():
            print("Video ended before 'After' frame. Saving last frame as 'After'.")
            frame_after = last_valid_frame if last_valid_frame is not None else frame
            if frame_after is not None:
                path_after = self.save_image(frame_after, current_sequence_id, current_incident_label, "3_after")
                current_snapshot_paths[2] = path_after
                final_snapshots = current_snapshot_paths
        
        # --- NEW FALLBACK LOGIC ---
        # If no snapshots generated at all, but we saw SOMETHING
        if not final_snapshots and best_fallback_data is not None:
            print(f"⚠️ No prolonged incident confirmed. Using FALLBACK snapshot (Best Conf: {best_fallback_conf:.2f})")
            fb_label, fb_before, fb_during = best_fallback_data
            fb_seq_id = int(time.time())
            
            p1 = self.save_image(fb_before, fb_seq_id, fb_label, "1_before")
            p2 = self.save_image(fb_during, fb_seq_id, fb_label, "2_during")
            # Use last frame as 'After'
            last_frame = last_valid_frame if last_valid_frame is not None else fb_during
            p3 = self.save_image(last_frame, fb_seq_id, fb_label, "3_after")
            
            final_snapshots = [p1, p2, p3]
            final_incident_id = fb_seq_id
            
            # Emit signals so UI updates
            self.detection_signal.emit(fb_label, p2)

        
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