import sys
import cv2
import numpy as np
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton, QTextEdit, QComboBox
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import pyqtSlot, Qt, QThread

from utils.detection_thread import DetectionThread
from utils.api_client import APIClient

class TrafficMonitorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Traffic Incident Reporter (Edge Client)")
        self.setGeometry(100, 100, 1200, 800)

        # UI Components
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Video Feed
        self.image_label = QLabel(self)
        self.image_label.resize(800, 600)
        self.layout.addWidget(self.image_label)

        self.source = 0 # Default to Webcam
        self.output_path = None
        
        # Controls
        self.btn_select = QPushButton("📂 Select Video", self)
        self.btn_select.clicked.connect(self.select_video)
        self.layout.addWidget(self.btn_select)

        # Model Selection
        self.lbl_model = QLabel("Select AI Model:", self)
        self.layout.addWidget(self.lbl_model)

        self.combo_model = QComboBox(self)
        self.combo_model.addItems(["Standard (Small)", "Premium (Medium)", "Premium V2 (New)"])
        self.combo_model.setCurrentIndex(1) # Default to Premium
        self.layout.addWidget(self.combo_model)

        # Confidence Threshold Slider
        self.lbl_conf = QLabel("Confidence Threshold: 0.70", self)
        self.layout.addWidget(self.lbl_conf)
        
        from PyQt6.QtWidgets import QSlider
        self.slider_conf = QSlider(Qt.Orientation.Horizontal, self)
        self.slider_conf.setRange(10, 100) # 0.10 to 1.00
        self.slider_conf.setValue(70)
        self.slider_conf.valueChanged.connect(self.update_conf_label)
        self.layout.addWidget(self.slider_conf)

        self.btn_start = QPushButton("Start Detection", self)
        self.btn_start.clicked.connect(self.start_detection)
        self.layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("Stop", self)
        self.btn_stop.clicked.connect(self.stop_detection)
        self.btn_stop.setEnabled(False)
        self.layout.addWidget(self.btn_stop)

        # Logs
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.layout.addWidget(self.log_output)

        # API Client
        self.api_client = APIClient()

        # Detection Thread
        self.thread = None

    def log(self, message):
        self.log_output.append(message)

    def select_video(self):
        from PyQt6.QtWidgets import QFileDialog
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Video Files (*.mp4 *.avi *.mkv)")
        if file_name:
            self.source = file_name
            self.log(f"Selected Video: {file_name}")
            
            # Auto-generate output path in 'd:\ProjectHTGTTM_CarTrafficReport\data'
            import os
            import uuid
            
            # Ensure data dir exists
            data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
                
            base_name = os.path.basename(file_name)
            name, ext = os.path.splitext(base_name)
            out_name = f"processed_{uuid.uuid4().hex[:8]}_{name}{ext}"
            self.output_path = os.path.join(data_dir, out_name)
            self.log(f"Output will be saved to: {self.output_path}")

    def start_detection(self):
        # Determine model path
        idx = self.combo_model.currentIndex()
        if idx == 1:
             model_path = 'model/medium/best.pt'
             self.log("Using Premium Model (Medium)")
        elif idx == 2:
             model_path = 'model/medium/mediumv2.pt'
             self.log("Using Premium V2 Model (New)")
        else:
             model_path = 'model/small/best.pt' 
             self.log("Using Standard Model (Small)") 
        
        if self.source == 0:
            self.log("Starting Webcam...")
        else:
            self.log(f"Processing File: {self.source}")
        
        conf_threshold = self.slider_conf.value() / 100.0
        self.thread = DetectionThread(model_path=model_path, source=self.source, save_path=self.output_path, conf_threshold=conf_threshold)
        self.thread.change_pixmap_signal.connect(self.update_image)
        self.thread.detection_signal.connect(self.handle_detection)
        self.thread.finished.connect(self.on_process_finished) # Handle completion
        self.thread.start()
        
        self.btn_start.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_stop.setEnabled(True)
    
    def on_process_finished(self):
        self.log("Processing Finished.")
        self.stop_detection()

    def stop_detection(self):
        if self.thread:
            self.thread.stop()
            self.thread = None
        
        self.btn_start.setEnabled(True)
        self.btn_select.setEnabled(True)
        self.btn_stop.setEnabled(False)
        # self.image_label.clear() # Optional: keep last frame
        self.log("Stopped.")

    @pyqtSlot(np.ndarray)
    def update_image(self, cv_img):
        qt_img = self.convert_cv_qt(cv_img)
        self.image_label.setPixmap(qt_img)

    def update_conf_label(self, value):
        self.lbl_conf.setText(f"Confidence Threshold: {value / 100.0:.2f}")

    @pyqtSlot(str, str)
    def handle_detection(self, class_name, image_path):
        self.log(f"ALERT: Detected {class_name}! Sending report...")
        
        # Send to API in a separate short-lived thread or async to avoid blocking UI
        # For simplicity here, we call a worker method (in real app, use QThread/QRunnable)
        response = self.api_client.send_incident(image_path, class_name)
        
        if response:
            self.log(f"Server Response: Reported ID {response.get('id')}")
        else:
            self.log("Failed to report Incident.")

    def convert_cv_qt(self, cv_img):
        """Convert from an opencv image to QPixmap"""
        rgb_image = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        convert_to_Qt_format = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        p = convert_to_Qt_format.scaled(800, 600, Qt.AspectRatioMode.KeepAspectRatio)
        return QPixmap.fromImage(p)

    def closeEvent(self, event):
        self.stop_detection()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TrafficMonitorApp()
    window.show()
    sys.exit(app.exec())
