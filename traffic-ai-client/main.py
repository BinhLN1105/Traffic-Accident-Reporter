import sys
import cv2
import numpy as np
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton, QTextEdit
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

        # Controls
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

    def start_detection(self):
        # Fixed path based on user input
        model_path = 'model/small/best.pt' 
        
        self.thread = DetectionThread(model_path=model_path, source=0) # 0 for Webcam
        self.thread.change_pixmap_signal.connect(self.update_image)
        self.thread.detection_signal.connect(self.handle_detection)
        self.thread.start()
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.log("System Started. Monitoring traffic...")

    def stop_detection(self):
        if self.thread:
            self.thread.stop()
            self.thread = None
        
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.image_label.clear()
        self.log("System Stopped.")

    @pyqtSlot(np.ndarray)
    def update_image(self, cv_img):
        qt_img = self.convert_cv_qt(cv_img)
        self.image_label.setPixmap(qt_img)

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
