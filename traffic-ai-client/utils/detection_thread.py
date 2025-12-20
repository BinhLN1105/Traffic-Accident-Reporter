import cv2
import time
from PyQt6.QtCore import QThread, pyqtSignal
from ultralytics import YOLO
import numpy as np

class DetectionThread(QThread):
    change_pixmap_signal = pyqtSignal(np.ndarray)
    detection_signal = pyqtSignal(str, str) # incident_type, image_path

    def __init__(self, model_path='best.pt', source=0):
        super().__init__()
        self.model_path = model_path
        self.source = source
        self.running = True
        self.model = None

    def run(self):
        # Load Model
        try:
            print(f"Loading model from {self.model_path}...")
            self.model = YOLO(self.model_path)
        except Exception as e:
            print(f"Error loading model: {e}")
            return

        # Open Webca
        cap = cv2.VideoCapture(self.source)
        
        last_alert_time = 0
        alert_cooldown = 5 # Seconds between alerts

        while self.running:
            ret, frame = cap.read()
            if not ret:
                break

            # YOLO Inference
            results = self.model(frame, verbose=False)
            annotated_frame = results[0].plot()

            # Check for detections
            current_time = time.time()
            if current_time - last_alert_time > alert_cooldown:
                for result in results:
                    for box in result.boxes:
                        class_id = int(box.cls[0])
                        class_name = self.model.names[class_id]
                        conf = float(box.conf[0])

                        # Filter for specific classes (adjust based on your dataset)
                        # Assuming your dataset has 'Accident', 'Fire' etc.
                        # For now, we take any detection > 0.6 confidence
                        if conf > 0.6: 
                            print(f"Detected {class_name} ({conf:.2f})")
                            
                            # Save snapshot
                            timestamp = int(time.time())
                            file_name = f"snapshot_{timestamp}.jpg"
                            cv2.imwrite(file_name, frame)
                            
                            # Emit signal to UI to send API request
                            self.detection_signal.emit(class_name, file_name)
                            
                            last_alert_time = current_time
                            break # Limit to 1 alert per frame

            # Update UI
            self.change_pixmap_signal.emit(annotated_frame)

        cap.release()

    def stop(self):
        self.running = False
        self.wait()
