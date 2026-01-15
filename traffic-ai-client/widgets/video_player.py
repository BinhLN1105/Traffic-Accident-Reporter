import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QSizePolicy
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, QUrl

class VideoPlayerWidget(QWidget):
    """Video player with playback controls"""
    
    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Video widget
        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # self.video_widget.setMinimumSize(400, 300) # Optional: much smaller min size
        layout.addWidget(self.video_widget)
        
        # Media player
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        
        # Load video
        if os.path.exists(self.video_path):
            self.player.setSource(QUrl.fromLocalFile(self.video_path))
        
        # Controls
        controls_layout = QHBoxLayout()
        
        # Play/Pause button
        self.btn_play = QPushButton("▶️ Play")
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_play.setMinimumHeight(40)
        controls_layout.addWidget(self.btn_play)
        
        # Stop button
        self.btn_stop = QPushButton("⏹️ Stop")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_stop.setMinimumHeight(40)
        controls_layout.addWidget(self.btn_stop)
        
        # Time label
        self.time_label = QLabel("00:00 / 00:00")
        controls_layout.addWidget(self.time_label)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Timeline slider
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setRange(0, 0)
        self.timeline.sliderMoved.connect(self.seek)
        layout.addWidget(self.timeline)
        
        # Connect signals
        self.player.durationChanged.connect(self.duration_changed)
        self.player.positionChanged.connect(self.position_changed)
        
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.btn_play.setText("▶️ Play")
        else:
            self.player.play()
            self.btn_play.setText("⏸️ Pause")
    
    def stop(self):
        self.player.stop()
        self.btn_play.setText("▶️ Play")
    
    def seek(self, position):
        self.player.setPosition(position)
    
    def duration_changed(self, duration):
        self.timeline.setRange(0, duration)
    
    def position_changed(self, position):
        self.timeline.setValue(position)
        
        # Update time label
        duration = self.player.duration()
        current = self.format_time(position)
        total = self.format_time(duration)
        self.time_label.setText(f"{current} / {total}")
    
    def format_time(self, ms):
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:02d}"
    
    def cleanup(self):
        """Cleanup player resources"""
        self.player.stop()
        self.player.setSource(QUrl())
