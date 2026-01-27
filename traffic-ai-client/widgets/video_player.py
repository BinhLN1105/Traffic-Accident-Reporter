import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QSizePolicy
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, QUrl

class VideoPlayerWidget(QWidget):
    """
    Widget phát video với các điều khiển phát lại
    Hỗ trợ play/pause, stop, và seek (tua đến vị trí cụ thể)
    """
    
    def __init__(self, video_path):
        """Khởi tạo player với đường dẫn video"""
        super().__init__()
        self.video_path = video_path
        self.setup_ui()
        
    def setup_ui(self):
        """Thiết lập giao diện người dùng cho video player"""
        layout = QVBoxLayout(self)
        
        # Widget hiển thị video
        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.video_widget)
        
        # Media player để điều khiển phát video
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        
        # Tải video nếu file tồn tại
        if os.path.exists(self.video_path):
            self.player.setSource(QUrl.fromLocalFile(self.video_path))
        
        # Các nút điều khiển
        controls_layout = QHBoxLayout()
        
        # Nút Play/Pause
        self.btn_play = QPushButton("▶️ Play")
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_play.setMinimumHeight(40)
        controls_layout.addWidget(self.btn_play)
        
        # Nút Stop
        self.btn_stop = QPushButton("⏹️ Stop")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_stop.setMinimumHeight(40)
        controls_layout.addWidget(self.btn_stop)
        
        # Nhãn hiển thị thời gian (hiện tại / tổng)
        self.time_label = QLabel("00:00 / 00:00")
        controls_layout.addWidget(self.time_label)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Thanh trượt timeline để seek (tua đến vị trí)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setRange(0, 0)
        self.timeline.sliderMoved.connect(self.seek)
        layout.addWidget(self.timeline)
        
        # Kết nối các signal để cập nhật UI khi video phát
        self.player.durationChanged.connect(self.duration_changed)
        self.player.positionChanged.connect(self.position_changed)
        
    def toggle_play(self):
        """
        Chuyển đổi giữa play và pause
        Logic: Kiểm tra trạng thái hiện tại và chuyển đổi
        """
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.btn_play.setText("▶️ Play")
        else:
            self.player.play()
            self.btn_play.setText("⏸️ Pause")
    
    def stop(self):
        """Dừng phát video và reset về đầu"""
        self.player.stop()
        self.btn_play.setText("▶️ Play")
    
    def seek(self, position):
        """
        Tua video đến vị trí cụ thể (theo milliseconds)
        Được gọi khi người dùng kéo thanh trượt timeline
        """
        self.player.setPosition(position)
    
    def duration_changed(self, duration):
        """
        Cập nhật phạm vi của thanh trượt khi biết độ dài video
        Được gọi khi video được tải và có thông tin về độ dài
        """
        self.timeline.setRange(0, duration)
    
    def position_changed(self, position):
        """
        Cập nhật vị trí thanh trượt và nhãn thời gian khi video phát
        Được gọi liên tục khi video đang phát để cập nhật UI
        """
        self.timeline.setValue(position)
        
        # Cập nhật nhãn thời gian (hiện tại / tổng)
        duration = self.player.duration()
        current = self.format_time(position)
        total = self.format_time(duration)
        self.time_label.setText(f"{current} / {total}")
    
    def format_time(self, ms):
        """
        Chuyển đổi milliseconds thành định dạng MM:SS
        Dùng để hiển thị thời gian trên UI
        """
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:02d}"
    
    def cleanup(self):
        """
        Dọn dẹp tài nguyên của player
        Nên gọi khi không dùng player nữa để giải phóng bộ nhớ
        """
        self.player.stop()
        self.player.setSource(QUrl())
