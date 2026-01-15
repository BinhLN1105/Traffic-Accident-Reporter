import sys
import cv2
import numpy as np
import signal  # For Ctrl+C handling
import os  # For file path checking
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QComboBox, QSlider,
    QTabWidget, QGroupBox, QFileDialog, QStatusBar, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QSizePolicy,
    QScrollArea, QStackedWidget, QProgressBar
)
from PyQt6.QtGui import QPixmap, QImage, QFont
from PyQt6.QtCore import pyqtSlot, Qt, QThread, QDateTime

from utils.detection_thread import DetectionThread
from utils.api_client import APIClient
from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtCore import pyqtSignal, QThread

class ReportWorker(QThread):
    finished = pyqtSignal(dict)
    
    def __init__(self, generator, snapshot_paths, incident_id, video_path=None):
        super().__init__()
        self.generator = generator
        self.snapshot_paths = snapshot_paths
        self.incident_id = incident_id
        self.video_path = video_path

    def run(self):
        try:
            # Generate the report in background
            # EXPECTS: before, during, after, incident_type, video_path
            
            # Ensure we have 3 snapshots (pad with None if needed)
            safe_snaps = self.snapshot_paths + [None] * (3 - len(self.snapshot_paths))
            incident_type = "vehicle accident" 
            
            result = self.generator.generate_report(
                safe_snaps[0], 
                safe_snaps[1],
                safe_snaps[2],
                incident_type,
                video_path=self.video_path
            )
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({'success': False, 'report': str(e)})

class TrafficMonitorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🚦 Smart Traffic Incident Reporter")
        self.setGeometry(50, 50, 1500, 950)  # Ensure window is large enough
        
        # Apply modern dark theme
        self.setStyleSheet(self.get_dark_theme())
        
        # State variables
        self.source = 0
        self.output_path = None
        self.detection_count = 0
        self.is_dark_mode = True # Track theme state
        self.api_client = APIClient()
        self.thread = None
        
        # Initialize AI report generator with API client
        from utils.report_generator import ReportGenerator
        self.report_generator = ReportGenerator(api_client=self.api_client)
        
        # Setup UI
        self.setup_ui()
        
    def setup_ui(self):
        # Central widget with tabs
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        
        # Tab widget
        self.tabs = QTabWidget()
        
        # Theme Toggle (Top Right Corner)
        self.btn_theme = QPushButton("🌓")
        self.btn_theme.setToolTip("Switch Theme (Light/Dark)")
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.btn_theme.setFixedSize(40, 30)
        self.btn_theme.setStyleSheet("border: none; font-size: 16px; background: transparent;")
        
        # Add to Tab Corner
        self.tabs.setCornerWidget(self.btn_theme, Qt.Corner.TopRightCorner)
        
        main_layout.addWidget(self.tabs)
        
        # Tab 1: Live Detection
        self.tab_live = QWidget()
        self.setup_live_tab()
        self.tabs.addTab(self.tab_live, "📹 Live Detection")
        
        # Tab 2: Video Analyst (NEW)
        self.tab_analyst = QWidget()
        self.setup_analyst_tab()
        self.tabs.addTab(self.tab_analyst, "🎞️ Video Analyst")
        
        # Tab 3: History
        self.tab_history = QWidget()
        self.setup_history_tab()
        self.tabs.addTab(self.tab_history, "📊 Detection History")
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
    def setup_live_tab(self):
        layout = QHBoxLayout(self.tab_live)
        
        # --- LEFT SIDE: SCROLL AREA ---
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Container inside ScrollArea
        left_container = QWidget()
        left_panel = QVBoxLayout(left_container)
        left_panel.setContentsMargins(0, 0, 10, 0) # Right margin for scrollbar
        left_panel.setSpacing(10)
        
        # 1. Video Area (Stack: 0=Live Feed, 1=Replay Player)
        self.stack_video = QStackedWidget()
        self.stack_video.setMinimumSize(1000, 700)
        self.stack_video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Page 0: Live Feed Label
        self.image_label = QLabel()
        self.image_label.setText("📹 No Video Feed")
        self.image_label.setStyleSheet("background: #1a1a1a; border: 2px solid #444; border-radius: 8px;")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack_video.addWidget(self.image_label)
        
        # Page 1: Placeholder for Video Player (Added dynamically)
        self.replay_container = QWidget()
        self.replay_layout = QVBoxLayout(self.replay_container)
        self.replay_layout.setContentsMargins(0,0,0,0)
        self.stack_video.addWidget(self.replay_container)
        
        left_panel.addWidget(self.stack_video, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        
        # 2. Snapshot Gallery
        self.snapshot_group = QGroupBox("📸 Detection Snapshots")
        snapshot_layout = QHBoxLayout()
        snapshot_layout.setContentsMargins(5, 15, 5, 5)
        snapshot_layout.setSpacing(15)
        
        # Create 3 image labels
        self.img_before = QLabel()
        self.img_during = QLabel()
        self.img_after = QLabel()
        
        # Store paths for zoom
        self.snapshot_paths = [None, None, None] 
        
        for idx, (img_label, text) in enumerate([
            (self.img_before, "Before"),
            (self.img_during, "During"), 
            (self.img_after, "After")
        ]):
            # Container for label + text
            container = QVBoxLayout()
            
            # Label Setup
            img_label.setFixedSize(300, 225) # Good size for visibility
            img_label.setStyleSheet("""
                QLabel {
                    background: #1a1a1a;
                    border: 2px solid #444;
                    border-radius: 6px;
                }
                QLabel:hover {
                    border: 2px solid #3b82f6; /* Blue border on hover */
                }
            """)
            img_label.setScaledContents(True)
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_label.setText("No Image")
            img_label.setToolTip("🔎 Click to Zoom")
            img_label.setCursor(Qt.CursorShape.PointingHandCursor)
            
            # Click event (Monkey patch mousePressEvent)
            # idx=idx capture variable
            def make_click_handler(index):
                return lambda event: self.show_full_image(index)
            
            img_label.mousePressEvent = make_click_handler(idx)
            
            # Label text
            label_text = QLabel(text)
            label_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label_text.setStyleSheet("color: #aaa; font-weight: bold; border: none; margin-top: 5px;")
            
            container.addWidget(img_label)
            container.addWidget(label_text)
            snapshot_layout.addLayout(container)
        
        self.snapshot_group.setLayout(snapshot_layout)
        
        left_panel.addWidget(self.snapshot_group, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        left_panel.addStretch(1) # Push everything up
        
        scroll_area.setWidget(left_container)
        layout.addWidget(scroll_area, 75) # Left side takes 75% width
        
        # Right: Controls - WRAP IN SCROLL AREA
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setMaximumWidth(480) # Main container limit

        right_container = QWidget()
        right_panel = QVBoxLayout(right_container)
        right_panel.setContentsMargins(10, 0, 10, 0) # Padding for visual breathing room
        
        # Source selection group
        source_group = QGroupBox("📂 Video Source")
        source_layout = QVBoxLayout()
        self.btn_select = QPushButton(" Select Video File")
        self.btn_select.clicked.connect(self.select_video)
        source_layout.addWidget(self.btn_select)
        source_group.setLayout(source_layout)
        right_panel.addWidget(source_group)
        
        # Model selection group
        model_group = QGroupBox("🤖 AI Model")
        model_layout = QVBoxLayout()
        self.combo_model = QComboBox()
        self.combo_model.addItems([
            "Standard (Small)",
            "Premium (Medium)",
            "Premium V2",
            "Premium V3 (Latest)"
        ])
        self.combo_model.setCurrentIndex(1)
        model_layout.addWidget(self.combo_model)
        model_group.setLayout(model_layout)
        right_panel.addWidget(model_group)
        
        # Confidence slider
        conf_group = QGroupBox("⚙️ Confidence Threshold")
        conf_layout = QVBoxLayout()
        self.lbl_conf = QLabel("Confidence: 0.70")
        self.slider_conf = QSlider(Qt.Orientation.Horizontal)
        self.slider_conf.setRange(10, 100)
        self.slider_conf.setValue(70)
        self.slider_conf.valueChanged.connect(self.update_conf_label)
        conf_layout.addWidget(self.lbl_conf)
        conf_layout.addWidget(self.slider_conf)
        conf_group.setLayout(conf_layout)
        right_panel.addWidget(conf_group)
        
        # AI Report selection
        ai_report_group = QGroupBox("📝 AI Report Generation")
        ai_layout = QVBoxLayout()
        self.combo_ai_model = QComboBox()
        self.combo_ai_model.addItems([
            "No Report (Image Only)",
            "Google Gemini (Cloud)",
            "Local LLM (Offline)"
        ])
        ai_layout.addWidget(self.combo_ai_model)
        
        # NEW: Manual Report Button
        self.btn_manual_report = QPushButton("📄 Generate Report Now")
        self.btn_manual_report.setToolTip("Generate report for the currently displayed snapshots")
        self.btn_manual_report.setEnabled(False) # Enabled only when snapshots exist
        self.btn_manual_report.clicked.connect(self.manual_report_generation)
        self.btn_manual_report.setStyleSheet("background: #d97706; border: 1px solid #b45309;") # Orange/Amber color
        ai_layout.addWidget(self.btn_manual_report)
        
        # NEW: View Report Button (for viewing result after generation)
        self.btn_view_report = QPushButton("👁️ View Latest Report")
        self.btn_view_report.setEnabled(False)
        self.btn_view_report.clicked.connect(lambda: self.show_report_dialog(
            self.last_report_text if hasattr(self, 'last_report_text') else "No Report", 
            self.snapshot_paths if hasattr(self, 'snapshot_paths') else []
        ))
        self.btn_view_report.setStyleSheet("background: #059669; border: 1px solid #047857;") # Emerald/Green
        ai_layout.addWidget(self.btn_view_report)
        
        ai_report_group.setLayout(ai_layout)
        right_panel.addWidget(ai_report_group)
        
        # Control buttons
        self.btn_start = QPushButton("▶️ Start Detection")
        self.btn_start.clicked.connect(self.start_detection)
        self.btn_start.setMinimumHeight(50)
        right_panel.addWidget(self.btn_start)
        
        self.btn_cancel = QPushButton("❌ Cancel Detection")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_detection)
        self.btn_cancel.setMinimumHeight(45)
        self.btn_cancel.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold;") 
        right_panel.addWidget(self.btn_cancel)
        
        # Toggle buttons & Log (Right Panel)
        toggle_layout = QHBoxLayout()
        
        self.btn_toggle_log = QPushButton("📜")
        self.btn_toggle_log.setToolTip("Toggle Activity Log")
        self.btn_toggle_log.clicked.connect(self.toggle_log)
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.setChecked(True)
        self.btn_toggle_log.setMaximumWidth(50)
        toggle_layout.addWidget(self.btn_toggle_log)
        
        self.btn_toggle_snapshots = QPushButton("📸")
        self.btn_toggle_snapshots.setToolTip("Toggle Snapshots")
        self.btn_toggle_snapshots.clicked.connect(self.toggle_snapshots)
        self.btn_toggle_snapshots.setCheckable(True)
        self.btn_toggle_snapshots.setChecked(True)
        self.btn_toggle_snapshots.setMaximumWidth(50)
        toggle_layout.addWidget(self.btn_toggle_snapshots)
        
        right_panel.addLayout(toggle_layout)
        
        # Activity Log (moved from left)
        self.log_group = QGroupBox("📜 Activity Log") # Make instance variable
        log_layout = QVBoxLayout()
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(200) # Slightly taller log
        log_layout.addWidget(self.log_output)
        
        self.log_group.setLayout(log_layout)
        right_panel.addWidget(self.log_group)
        
        right_panel.addStretch() # Ensure stretch is AT THE END
        
        right_scroll.setWidget(right_container)
        layout.addWidget(right_scroll)
        
    def setup_analyst_tab(self):
        """Setup Modern Video Analyst Interface"""
        # Main Layout (Scrollable Wrapper)
        main_layout = QVBoxLayout(self.tab_analyst)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        
        # Scrollable Content
        content_widget = QWidget()
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)
        
        # Horizontal Split Layout (Left: Video, Right: Settings)
        layout = QHBoxLayout(content_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # --- LEFT: Video (Big Area) ---
        container_left = QWidget()
        layout_left = QVBoxLayout(container_left)
        layout_left.setContentsMargins(0,0,10,0)
        
        # 1. Video Stack (Flexible Sizing)
        self.analyst_stack = QStackedWidget()
        self.analyst_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # self.analyst_stack.setMinimumSize(900, 500) # REMOVED FIXED SIZE
        self.analyst_stack.setMinimumHeight(400) # Smaller reasonable min height
        
        # Page 0: Upload Prompt
        self.page_upload = QWidget()
        layout_upload = QVBoxLayout(self.page_upload)
        
        lbl_icon = QLabel("📂")
        lbl_icon.setStyleSheet("font-size: 64px; color: #555; border: none;")
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        lbl_text = QLabel("Select a Video File to Begin Analysis")
        lbl_text.setStyleSheet("font-size: 18px; color: #888; font-weight: bold; border: none;")
        lbl_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        btn_browse_big = QPushButton("Browse Files")
        btn_browse_big.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_big.setFixedSize(200, 50)
        btn_browse_big.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6; color: white; border-radius: 25px; font-size: 16px;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        btn_browse_big.clicked.connect(self.select_analyst_video)
        
        layout_upload.addStretch()
        layout_upload.addWidget(lbl_icon)
        layout_upload.addWidget(lbl_text)
        layout_upload.addWidget(btn_browse_big, 0, Qt.AlignmentFlag.AlignHCenter)
        layout_upload.addStretch()
        
        self.analyst_stack.addWidget(self.page_upload)
        
        # Page 1: Video Player Container
        self.analyst_player_container = QWidget()
        self.analyst_player_layout = QVBoxLayout(self.analyst_player_container)
        self.analyst_player_layout.setContentsMargins(0,0,0,0)
        
        # Loading / Progress UI (Initially Hidden)
        self.analyst_loading_container = QWidget(self.analyst_player_container)
        self.analyst_loading_layout = QVBoxLayout(self.analyst_loading_container)
        self.analyst_loading_container.hide()
        
        self.lbl_analyst_loading = QLabel("Analyzing Video... 0%")
        self.lbl_analyst_loading.setStyleSheet("font-size: 24px; color: #3b82f6; font-weight: bold;")
        self.lbl_analyst_loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.analyst_progress = QProgressBar()
        self.analyst_progress.setRange(0, 100)
        self.analyst_progress.setValue(0)
        self.analyst_progress.setTextVisible(False)
        self.analyst_progress.setFixedHeight(10)
        self.analyst_progress.setStyleSheet("""
            QProgressBar { border-radius: 5px; background: #333; }
            QProgressBar::chunk { background: #3b82f6; border-radius: 5px; }
        """)
        
        self.analyst_loading_layout.addStretch()
        self.analyst_loading_layout.addWidget(self.lbl_analyst_loading)
        self.analyst_loading_layout.addWidget(self.analyst_progress)
        self.analyst_loading_layout.addStretch()
        
        self.analyst_player_layout.addWidget(self.analyst_loading_container)
        
        self.analyst_stack.addWidget(self.analyst_player_container)
        
        layout_left.addWidget(self.analyst_stack, 70) 

        # 2. Snapshot Gallery (Initially Hidden)
        self.analyst_snapshot_group = QGroupBox("📸 Analysis Results")
        self.analyst_snapshot_layout = QHBoxLayout()
        self.analyst_snapshot_layout.setSpacing(15)
        
        self.lbl_analyst_res_before = QLabel("Before")
        self.lbl_analyst_res_during = QLabel("During")
        self.lbl_analyst_res_after = QLabel("After")
        
        # Style the labels
        for lbl in [self.lbl_analyst_res_before, self.lbl_analyst_res_during, self.lbl_analyst_res_after]:
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("border: 1px dashed #666; background: #222; color: #888;")
            lbl.setFixedSize(280, 160) 
            lbl.setScaledContents(True)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor) # Make clickable
            
            # Enable Click to View via lambda binding
            lbl.mousePressEvent = lambda event, l=lbl: self.on_snapshot_click(l)
            
            self.analyst_snapshot_layout.addWidget(lbl)
            
        self.analyst_snapshot_group.setLayout(self.analyst_snapshot_layout)
        self.analyst_snapshot_group.hide() # Hide until analysis done
        
        layout_left.addWidget(self.analyst_snapshot_group, 30)
        
        # --- RIGHT: Controls & Results ---
        # Wrapper for Scroll Area
        # Wrapper for Scroll Area
        container_right_wrapper = QWidget()
        container_right_wrapper.setMaximumWidth(420) 
        container_right_wrapper.setObjectName("analystRightPanelWrapper") # IDs for Theming
        layout_right_wrapper = QVBoxLayout(container_right_wrapper)
        layout_right_wrapper.setContentsMargins(0,0,0,0)
        
        # Scroll Area
        scroll_right = QScrollArea()
        scroll_right.setWidgetResizable(True)
        scroll_right.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_right.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Content Widget
        container_right = QWidget()
        container_right.setObjectName("analystRightPanel") # IDs for Theming
        layout_right = QVBoxLayout(container_right)
        layout_right.setSpacing(20)
        
        scroll_right.setWidget(container_right)
        layout_right_wrapper.addWidget(scroll_right)
        
        # Header
        lbl_r_header = QLabel("⚙️ Analysis Settings")
        lbl_r_header.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout_right.addWidget(lbl_r_header)
        
        # Selected File Info
        self.lbl_selected_file = QLabel("No file selected")
        self.lbl_selected_file.setWordWrap(True)
        self.lbl_selected_file.setObjectName("lblSelectedFile") # Use ID instead of inline style
        layout_right.addWidget(self.lbl_selected_file)

        # --- Detection Controls ---
        grp_detect = QGroupBox("🔍 Detection Configuration")
        # Inline style removed, will use global theme
        layout_detect = QVBoxLayout(grp_detect)

        # Model Selector
        lbl_model = QLabel("Select YOLO Model:")
        self.scan_model_combo = QComboBox()
        self.scan_model_combo.addItems(["model/small/best.pt", "model/medium/mediumv3.pt", "model/nano/nano.pt"])
        self.scan_model_combo.setCurrentIndex(1) 
        layout_detect.addWidget(lbl_model)
        layout_detect.addWidget(self.scan_model_combo)

        # Confidence Slider
        lbl_conf = QLabel("Confidence Threshold:")
        self.lbl_conf_val = QLabel("70%")
        self.lbl_conf_val.setStyleSheet("color: #3b82f6; font-weight: bold;") # This color is fine for both
        
        row_conf = QHBoxLayout()
        row_conf.addWidget(lbl_conf)
        row_conf.addStretch()
        row_conf.addWidget(self.lbl_conf_val)
        
        self.scan_conf_slider = QSlider(Qt.Orientation.Horizontal)
        self.scan_conf_slider.setRange(0, 100)
        self.scan_conf_slider.setValue(70)
        self.scan_conf_slider.valueChanged.connect(lambda v: self.lbl_conf_val.setText(f"{v}%"))
        
        layout_detect.addWidget(lbl_conf)  # Re-add label line if layout needs vertical stacking
        layout_detect.addLayout(row_conf)
        layout_detect.addWidget(self.scan_conf_slider)
        
        layout_right.addWidget(grp_detect)

        # --- AI Reporting Controls ---
        # --- AI Reporting Controls ---
        grp_report = QGroupBox("📝 AI Report Settings")
        # Removed inline style: grp_report.setStyleSheet(grp_detect.styleSheet())
        layout_report = QVBoxLayout(grp_report)

        # Auto Checkbox
        self.chk_auto_report = QCheckBox("Auto-Generate Report")
        self.chk_auto_report.setToolTip("Automatically generate AI report after video analysis finishes")
        layout_report.addWidget(self.chk_auto_report)

        # AI Model Selector
        lbl_ai = QLabel("AI Model Providers:")
        self.scan_ai_combo = QComboBox()
        self.scan_ai_combo.addItems(["Gemini Cloud AI", "Local LLM (Coming Soon)", "None"])
        layout_report.addWidget(lbl_ai)
        layout_report.addWidget(self.scan_ai_combo)

        layout_right.addWidget(grp_report)
        
        # Action Buttons
        self.btn_analyze = QPushButton("⚡ Start Analysis")
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setMinimumHeight(45)
        self.btn_analyze.setStyleSheet("""
            QPushButton { background-color: #10b981; color: white; font-weight: bold; border-radius: 6px; }
            QPushButton:disabled { background-color: #333; color: #555; }
            QPushButton:hover { background-color: #059669; }
        """)
        self.btn_analyze.clicked.connect(self.start_analysis)
        layout_right.addWidget(self.btn_analyze)
        
        # Manual Report Button
        self.btn_analyst_report = QPushButton("📝 Generate Report")
        self.btn_analyst_report.setEnabled(False)
        self.btn_analyst_report.clicked.connect(lambda: self.manual_report_generation()) 
        self.btn_analyst_report.setStyleSheet("background: #d97706; border: 1px solid #b45309; padding: 10px; color: white;")
        layout_right.addWidget(self.btn_analyst_report)
        
        # View Report Button (Hidden initially)
        self.btn_view_report = QPushButton("📄 View Last Report")
        self.btn_view_report.hide()
        self.btn_view_report.clicked.connect(self.view_last_report)
        self.btn_view_report.setStyleSheet("background: #3b82f6; border: 1px solid #2563eb; padding: 10px; color: white;")
        layout_right.addWidget(self.btn_view_report)
        
        # Progress Bar / Status
        self.lbl_status_analyst = QLabel("Ready")
        self.lbl_status_analyst.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status_analyst.setObjectName("lblAnalystStatus") 
        layout_right.addWidget(self.lbl_status_analyst)
        
        layout_right.addStretch()
        
        layout.addWidget(container_left, 70) 
        layout.addWidget(container_right_wrapper, 30)

    def on_snapshot_click(self, label):
        """Handle click on analyst snapshot label"""
        path = label.property("file_path")
        if path and os.path.exists(path):
            self.show_image_dialog(path)

    def setup_history_tab(self):
        layout = QVBoxLayout(self.tab_history)
        
        # Header
        header_layout = QHBoxLayout()
        label = QLabel("📊 Detection History")
        label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header_layout.addWidget(label)
        
        # Refresh button
        btn_refresh = QPushButton("🔄 Refresh")
        btn_refresh.clicked.connect(self.load_history)
        btn_refresh.setMaximumWidth(150)
        header_layout.addWidget(btn_refresh)
        
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Table widget
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(["ID", "Timestamp", "Type", "Location", "Report"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.verticalHeader().setVisible(False) # HIDE ROW NUMBERS
        self.history_table.setAlternatingRowColors(True)
        
        # Set column widths
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(4, 100)
        
        # Set table properties
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setSortingEnabled(True)
        
        layout.addWidget(self.history_table)
        
        # Auto-load on tab creation
        self.load_history()
    
    def load_history(self):
        """Load detection history from Java backend"""
        self.log("📊 Loading history from backend...")
        
        incidents = self.api_client.get_history(limit=100)
        
        self.history_table.setRowCount(0)  # Clear existing
        
        for incident in incidents:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            
            # ID
            self.history_table.setItem(row, 0, QTableWidgetItem(str(incident.get('id', ''))))
            
            # Timestamp
            timestamp = incident.get('timestamp', '')
            self.history_table.setItem(row, 1, QTableWidgetItem(timestamp))
            
            # Type
            incident_type = incident.get('type', 'Unknown')
            self.history_table.setItem(row, 2, QTableWidgetItem(incident_type))
            
            # Location
            location = incident.get('location', 'N/A')
            self.history_table.setItem(row, 3, QTableWidgetItem(location))
            
            # View Report button
            btn_view = QPushButton("View")
            btn_view.clicked.connect(lambda checked, inc=incident: self.view_incident_detail(inc))
            self.history_table.setCellWidget(row, 4, btn_view)
        
        self.log(f"✅ Loaded {len(incidents)} historical incidents")
    
    def view_incident_detail(self, incident):
        """Show incident detail dialog"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton, QScrollArea, QWidget, QHBoxLayout
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"🔍 Incident Detail - ID: {incident.get('id')}")
        dialog.resize(900, 800)
        
        layout = QVBoxLayout(dialog)
        
        # Basic info
        info_text = f"<h2>Incident Report #{incident.get('id')}</h2>"
        info_text += f"<p><b>Type:</b> {incident.get('type')}<br>"
        info_text += f"<b>Time:</b> {incident.get('timestamp')}<br>"
        info_text += f"<b>Location:</b> {incident.get('location')}</p>"
        
        info_label = QLabel(info_text)
        info_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info_label)
        
        # Helper to clean JSON string if needed
        def parse_snapshot_urls(json_str):
            import json
            try:
                if not json_str: return []
                if isinstance(json_str, list): return json_str
                if json_str.startswith("["): return json.loads(json_str)
                return []
            except Exception as e:
                # self.log(f"JSON Parse Error: {e}") 
                return []

        # --- Snapshot Gallery ---
        snapshot_urls = parse_snapshot_urls(incident.get('snapshotUrls'))
        if snapshot_urls:
            lbl_gallery = QLabel(f"📸 Snapshot Gallery ({len(snapshot_urls)} images)")
            lbl_gallery.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
            layout.addWidget(lbl_gallery)
            
            # Imports are now at top of function
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFixedHeight(220)
            
            gallery_widget = QWidget()
            gallery_layout = QHBoxLayout(gallery_widget)
            
            labels = ["Before", "During", "After"]
            
            # Resolve Data Directory
            data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
            
            for i, path_url in enumerate(snapshot_urls):
                if i >= 3: break
                
                v_box = QVBoxLayout()
                
                # Image
                img_lbl = QLabel()
                img_lbl.setFixedSize(280, 180)
                img_lbl.setScaledContents(True)
                img_lbl.setStyleSheet("border: 1px solid #555;")
                
                # Path Resolution Logic
                local_path = None
                if isinstance(path_url, str):
                    if path_url.startswith("/api"):
                        # It's a URL from backend, look for filename in local data folder
                        filename = path_url.split("/")[-1]
                        local_path = os.path.join(data_dir, filename)
                    elif os.path.isabs(path_url):
                        local_path = path_url
                    else:
                        local_path = os.path.join(data_dir, os.path.basename(path_url))
                
                if local_path and os.path.exists(local_path):
                     img_lbl.setPixmap(QPixmap(local_path))
                else:
                     img_lbl.setText(f"Missing File\n{os.path.basename(path_url) if isinstance(path_url, str) else 'Invalid'}")
                     img_lbl.setStyleSheet("border: 1px dashed red; color: red;")
                     img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                
                # Label
                txt_lbl = QLabel(labels[i] if i < 3 else f"Image {i+1}")
                txt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                txt_lbl.setStyleSheet("font-weight: bold; color: #888;")
                
                v_box.addWidget(img_lbl)
                v_box.addWidget(txt_lbl)
                gallery_layout.addLayout(v_box)
                
            scroll.setWidget(gallery_widget)
            layout.addWidget(scroll)

        # --- Video Replay ---
        # Note: Backend might send 'videoUrl' or 'imageUrl' (legacy)
        # We check both or specific field.
        raw_video = incident.get('videoUrl') # Use videoUrl first
        if not raw_video:
             raw_video = incident.get('imageUrl') if str(incident.get('imageUrl')).endswith('.mp4') else None
        
        btn_video = QPushButton("🎬 Play Incident Video")
        btn_video.setStyleSheet("background-color: #3b82f6; color: white; font-weight: bold; padding: 8px; border-radius: 4px;")
        
        if raw_video and isinstance(raw_video, str):
             # Resolve video path similarly
             vid_name = raw_video.split("/")[-1]
             local_vid_path = os.path.join(data_dir, vid_name)
             
             if os.path.exists(local_vid_path):
                btn_video.setEnabled(True)
                btn_video.clicked.connect(lambda: self.show_video_player(local_vid_path))
             else:
                btn_video.setText(f"🎬 Video Not Found")
                btn_video.setEnabled(False)
                btn_video.setStyleSheet("background-color: #555; color: #aaa; padding: 8px;")
        else:
             btn_video.setText("🎬 Video Not Available")
             btn_video.setEnabled(False)
             btn_video.setStyleSheet("background-color: #555; color: #aaa; padding: 8px;")
             
        layout.addWidget(btn_video)

        # AI Report
        if incident.get('aiReport'):
            report_label = QLabel("📝 AI Report:")
            report_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
            layout.addWidget(report_label)
            
            report_text = QTextEdit()
            report_text.setReadOnly(True)
            report_text.setMarkdown(incident['aiReport'])
            # Increase font size for readability
            font = report_text.font()
            font.setPointSize(11)
            report_text.setFont(font)
            layout.addWidget(report_text)
        else:
            layout.addWidget(QLabel("⚠️ No AI report available"))
        
        # Close button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dialog.close)
        layout.addWidget(btn_close)
        
        dialog.exec()

    def log(self, message):
        self.log_output.append(message)
    
    def toggle_log(self):
        """Toggle Activity Log visibility"""
        if hasattr(self, 'log_group'):
            # Toggle visibility
            is_visible = self.btn_toggle_log.isChecked()
            self.log_group.setVisible(is_visible)
    
    def toggle_snapshots(self):
        """Toggle Snapshot Gallery visibility"""
        # Kiểm tra xem biến đã được khởi tạo chưa để tránh lỗi
        if hasattr(self, 'snapshot_group'):
            is_visible = self.btn_toggle_snapshots.isChecked()
            
            # Cách chuẩn: Dùng setVisible
            self.snapshot_group.setVisible(is_visible)

    def select_video(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, 
            "Select Video", 
            "", 
            "Video Files (*.mp4 *.avi *.mkv *.mov)"
        )
        if file_name:
            self.source = file_name
            self.log(f"✅ Selected: {file_name}")
            
            # Auto-generate output path
            import os
            import uuid
            
            data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
                
            base_name = os.path.basename(file_name)
            name, ext = os.path.splitext(base_name)
            out_name = f"processed_{uuid.uuid4().hex[:8]}_{name}{ext}"
            self.output_path = os.path.join(data_dir, out_name)
            self.log(f"📁 Output: {self.output_path}")
            
            # Update UI to show video is selected
            self.image_label.setText(f"🎬 Ready to Play: {os.path.basename(file_name)}\nClick 'Start Detection' to begin")
            self.image_label.setStyleSheet("background: #1a1a1a; border: 2px solid #3b82f6; border-radius: 8px; color: #3b82f6; font-size: 18px; font-weight: bold;")

    def start_detection(self):
        # Determine model path based on combo box selection
        idx = self.combo_model.currentIndex()
        if idx == 0:
             model_path = 'model/small/best.pt'
             self.log("Using Standard Model (Small)")
        elif idx == 1:
             model_path = 'model/medium/best.pt'
             self.log("Using Premium Model (Medium)")
        elif idx == 2:
             model_path = 'model/medium/mediumv2.pt'
             self.log("Using Premium V2 Model")
        elif idx == 3:
             model_path = 'model/medium/mediumv3.pt'
             self.log("Using Premium V3 Model (Latest)")
        else:
             model_path = 'model/small/best.pt'  # Fallback
             self.log("Using Standard Model (Small - Fallback)") 
        
        if self.source == 0:
            self.log("Starting Webcam...")
        else:
            self.log(f"Processing File: {self.source}")
        
        conf_threshold = self.slider_conf.value() / 100.0
        self.thread = DetectionThread(model_path=model_path, source=self.source, save_path=self.output_path, conf_threshold=conf_threshold)
        self.thread.change_pixmap_signal.connect(self.update_image)
        self.thread.detection_signal.connect(self.handle_detection)
        self.thread.snapshot_saved.connect(self.display_snapshots)  # NEW: Connect snapshot signal
        self.thread.finished.connect(self.on_process_finished) # Handle completion
        self.thread.start()
        
        self.btn_start.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_cancel.setEnabled(True)
    
    def on_process_finished(self):
        """Called when detection thread finishes naturally or is stopped"""
        self.status_bar.showMessage("✅ Detection Finished")
        self.log("✅ Processing complete.")
        
        # Reset UI Button States
        self.update_control_buttons("IDLE")
        
        # --- LATE REPORT GENERATION ---
        # Generate report only after video finishes to avoid partial results
        if hasattr(self, 'snapshot_paths') and all(self.snapshot_paths) and self.combo_ai_model.currentIndex() > 0:
             self.log("🤖 Video finished. Generating Final AI Report...")
             QApplication.processEvents()
             
             path_before, path_during, path_after = self.snapshot_paths
             incident_type = "vehicle accident" # Could use self.last_detection_type if stored
             
             # Call generator with VIDEO path
             video_path_to_send = self.output_path if self.output_path and os.path.exists(self.output_path) else None
             self.log(f"📤 Uploading report with video: {os.path.basename(video_path_to_send) if video_path_to_send else 'None'}")
             
             result = self.report_generator.generate_report(
                 path_before, path_during, path_after, incident_type, video_path=video_path_to_send
             )
             
             if result['success']:
                self.log(f"✅ Final Report Generated! ID: {result['incident_id']}")
                self.last_report_text = result['report']
                if hasattr(self, 'btn_view_report'): self.btn_view_report.setEnabled(True)
                self.show_report_dialog(result['report'], [path_before, path_during, path_after])
             else:
                self.log(f"⚠️ Report Generation Failed: {result.get('report', 'Unknown error')}")
                self.last_report_text = result.get('report', 'Unknown error')
                if hasattr(self, 'btn_view_report'): self.btn_view_report.setEnabled(True)
                self.show_report_dialog(result.get('report', 'Unknown error'), [path_before, path_during, path_after])
        
        # Show output video if available
        if self.output_path and os.path.exists(self.output_path):
            self.log(f"🎬 Loading playback: {os.path.basename(self.output_path)}")
            self.show_video_player(self.output_path)
    
    def show_video_player(self, video_path):
        """Show video player embedded in the main stack"""
        try:
            from widgets.video_player import VideoPlayerWidget
            
            # Clear previous player if exists
            for i in range(self.replay_layout.count()):
                item = self.replay_layout.itemAt(i)
                if item.widget():
                    item.widget().deleteLater()
            
            # Add video player to the replay container
            self.player_widget = VideoPlayerWidget(video_path)
            self.replay_layout.addWidget(self.player_widget)
            
            # Switch Stack to Page 1 (Replay)
            self.stack_video.setCurrentIndex(1)
            
            # Add "Back to Live" button to the player widget area or right panel
            # For now, simply starting a new detection should switch back
            
            self.log("✅ Video player loaded in Analyst View")
            
        except ImportError as e:
            self.log(f"⚠️ Video player unavailable: {e}")
            self.log("💡 Install: pip install PyQt6-Multimedia")
    
    # --- ANALYST TAB LOGIC ---
    # --- ANALYST TAB LOGIC ---
    @pyqtSlot(int)
    def update_analyst_progress(self, val):
        """Update progress bar during analysis"""
        self.analyst_progress.setValue(val)
        self.lbl_analyst_loading.setText(f"Analyzing... {val}%")

    @pyqtSlot(str, str)
    def handle_analyst_detection(self, label, conf):
        """Handle detections from analyst thread"""
        # Optional: Log or just ignore since we wait for finish
        pass 

    def start_analysis(self):
        """Start analysis with selected file and settings"""
        if not hasattr(self, 'analyst_file_path') or not self.analyst_file_path:
            return
            
        # Get settings from NEW UI controls
        model_path = self.scan_model_combo.currentText().strip()
        conf_threshold = self.scan_conf_slider.value() / 100.0
        
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setText("⏳ Analyzing...")
        self.lbl_status_analyst.setText("Starting Analysis...")
        self.lbl_status_analyst.setStyleSheet("color: #fbbf24;")
        
        # Clear previous results (Optional, since group is hidden, but good for reset)
        if hasattr(self, 'lbl_analyst_res_before'):
            self.lbl_analyst_res_before.setText("Waiting...")
            self.lbl_analyst_res_before.setPixmap(QPixmap())
        
        # UI: Switch to Progress View
        self.analyst_stack.setCurrentIndex(1)
        self.analyst_loading_container.show()
        if hasattr(self, 'analyst_snapshot_group'): 
             self.analyst_snapshot_group.hide() # Hide results during processing
        
        # Cleanup Player Stack Page if needed
        for i in range(self.analyst_player_layout.count()):
             item = self.analyst_player_layout.itemAt(i)
             if item.widget() and item.widget() != self.analyst_loading_container:
                 item.widget().deleteLater()
                 
        if self.analyst_loading_container.parent() is None:
             self.analyst_player_layout.addWidget(self.analyst_loading_container)
        
        # Generate Output Path
        output_dir = "data/analyst_output"
        os.makedirs(output_dir, exist_ok=True)
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")
        save_path = f"{output_dir}/analyst_{timestamp}.mp4"
        
        # Start Thread
        self.analyst_thread = DetectionThread(
            source=self.analyst_file_path,
            model_path=model_path,
            conf_threshold=conf_threshold,
            save_path=save_path
        )
        # NO Live Preview Connection
        # self.analyst_thread.change_pixmap_signal.connect(self.update_analyst_preview)
        
        self.analyst_thread.progress_signal.connect(self.update_analyst_progress)
        self.analyst_thread.detection_signal.connect(self.handle_analyst_detection)
        self.analyst_thread.process_finished_signal.connect(self.on_analyst_finished)
        self.analyst_thread.start()

    def on_analyst_finished(self, result_data):
        """Called when analysis is 100% done"""
        self.btn_analyze.setEnabled(True)
        self.btn_analyze.setText("⚡ Start Analysis")
        self.lbl_status_analyst.setText("✅ Analysis Complete.")
        self.lbl_status_analyst.setStyleSheet("color: #10b981;")
        
        # Hide Progress (Check existence first)
        if hasattr(self, 'analyst_loading_container'):
             self.analyst_loading_container.hide()
             
        # Extract Results
        output_path = result_data.get('output_path')
        result_snapshots = result_data.get('snapshots', [])
        incident_id = result_data.get('incident_id')
        
        # 1. SHOW PROCESSED VIDEO
        if output_path and os.path.exists(output_path):
             self.show_analyst_player(output_path)
             self.output_path = output_path 
             
        # 2. SHOW SNAPSHOTS (Bottom)
        self.snapshot_paths = result_snapshots 
        
        # Map snapshots to labels: Before, During, After
        # Ensure we have enough snapshots or pad
        while len(result_snapshots) < 3: result_snapshots.append(None)
        
        pairs = [
            (result_snapshots[0], self.lbl_analyst_res_before),
            (result_snapshots[1], self.lbl_analyst_res_during),
            (result_snapshots[2], self.lbl_analyst_res_after)
        ]
        
        for path, lbl in pairs:
            if path and os.path.exists(path):
                lbl.setPixmap(QPixmap(path).scaled(280, 160, Qt.AspectRatioMode.KeepAspectRatio))
                lbl.setProperty("file_path", path) # Store path for click event
                
        if hasattr(self, 'analyst_snapshot_group'):
            self.analyst_snapshot_group.show() 
        
        # Enable Manual Report
        self.btn_analyst_report.setEnabled(True)
        
        # Handle Auto-Report
        if self.chk_auto_report.isChecked():
            # Trigger report generation worker
            self.start_report_worker(result_snapshots, incident_id, output_path)

        # Update button to call worker manually if not auto
        try: self.btn_analyst_report.clicked.disconnect() 
        except: pass
        self.btn_analyst_report.clicked.connect(lambda: self.start_report_worker(result_snapshots, incident_id, output_path))

    def start_report_worker(self, snapshots, incident_id, video_path):
        """Start the background report worker"""
        self.btn_analyst_report.setEnabled(False)
        self.lbl_status_analyst.setText("⏳ AI Generating Report...")
        
        self.report_worker = ReportWorker(self.report_generator, snapshots, incident_id, video_path)
        self.report_worker.finished.connect(self.on_report_worker_finished)
        self.report_worker.start()

    def on_report_worker_finished(self, result):
        """Handle background report completion"""
        self.btn_analyst_report.setEnabled(True)
        self.btn_analyst_report.setText("📝 Generate Report")
        
        if result['success']:
            self.lbl_status_analyst.setText("✅ Report Generated!")
            self.last_report_result = result['report'] # Store for re-viewing
            
            # Show "View Report" button
            self.btn_view_report.show()
            
            self.show_report_dialog(result['report'], self.snapshot_paths)
        else:
            self.lbl_status_analyst.setText("⚠️ Report Failed")
            self.show_report_dialog(result.get('report', 'Error'), self.snapshot_paths)

    def view_last_report(self):
        """Re-open the last generated report"""
        if hasattr(self, 'last_report_result') and self.last_report_result:
            self.show_report_dialog(self.last_report_result, self.snapshot_paths)

    def manual_report_generation(self):
        """Manually trigger AI report for current snapshots"""
        if not hasattr(self, 'snapshot_paths') or not all(self.snapshot_paths):
            self.log("⚠️ No snapshots available to report on.")
            return

        self.log("📝 Generating Manual Report...")
        path_before, path_during, path_after = self.snapshot_paths
        
        # Force select Gemini if it was on "No Report"
        if self.combo_ai_model.currentIndex() == 0:
            self.combo_ai_model.setCurrentIndex(1) # Select Gemini
            self.log("💡 Switched to Gemini model.")

        incident_type = "vehicle accident"
        result = self.report_generator.generate_report(
            path_before, path_during, path_after, incident_type
        )
        
        if result['success']:
            self.log(f"✅ AI Report generated! Incident ID: {result['incident_id']}")
            self.show_report_dialog(result['report'], [path_before, path_during, path_after])
        else:
            self.log(f"⚠️ Report error: {result['report']}")
            self.show_report_dialog(result['report'], [path_before, path_during, path_after])

    def show_report_dialog(self, report_text: str, image_paths: list = None):
        """Show AI report in a dialog with optional images"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel, QScrollArea
        
        dialog = QDialog(self)
        dialog.setWindowTitle("📝 AI Incident Report")
        dialog.resize(900, 800)
        
        layout = QVBoxLayout(dialog)
        
        # --- Image Gallery Section ---
        if image_paths and all(image_paths):
            lbl_gallery = QLabel("📸 Snapshot Gallery")
            lbl_gallery.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
            layout.addWidget(lbl_gallery)
            
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFixedHeight(220)
            
            gallery_widget = QWidget()
            gallery_layout = QHBoxLayout(gallery_widget)
            
            labels = ["Before", "During", "After"]
            for i, path in enumerate(image_paths):
                if i >= 3: break
                
                v_box = QVBoxLayout()
                
                # Image
                img_lbl = QLabel()
                img_lbl.setFixedSize(280, 180)
                img_lbl.setScaledContents(True)
                img_lbl.setStyleSheet("border: 1px solid #555;")
                if path and os.path.exists(path):
                    img_lbl.setPixmap(QPixmap(path))
                else:
                    img_lbl.setText("Image not found")
                
                # Label
                txt_lbl = QLabel(labels[i] if i < 3 else f"Image {i+1}")
                txt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                txt_lbl.setStyleSheet("font-weight: bold; color: #888;")
                
                v_box.addWidget(img_lbl)
                v_box.addWidget(txt_lbl)
                gallery_layout.addLayout(v_box)
                
            scroll.setWidget(gallery_widget)
            layout.addWidget(scroll)
        
        # --- Report Text Section ---
        lbl_report = QLabel("📝 Analysis Result")
        lbl_report.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
        layout.addWidget(lbl_report)
        
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setMarkdown(report_text) # Use markdown rendering
        layout.addWidget(text_edit)
        
        # Close button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dialog.close)
        layout.addWidget(btn_close)
        
        dialog.show()
        self.log("✅ Report dialog opened")

    def show_image_dialog(self, image_path):
        """Show full size image in a simple dialog"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtCore import Qt
        
        if not image_path or not os.path.exists(image_path):
            self.log("⚠️ Image path invalid")
            return
            
        dialog = QDialog(self)
        dialog.setWindowTitle(f"🔍 View Image: {os.path.basename(image_path)}")
        dialog.resize(1000, 800)
        
        layout = QVBoxLayout(dialog)
        
        # Scroll Area for large images
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        
        # Image Label
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("background: #000;")
        
        pixmap = QPixmap(image_path)
        
        # Scale up if image is smaller than dialog view (approx 950x750)
        view_w, view_h = 950, 750
        if pixmap.width() < view_w or pixmap.height() < view_h:
            pixmap = pixmap.scaled(view_w, view_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            
        lbl.setPixmap(pixmap)
        
        scroll.setWidget(lbl)
        
        dialog.show()
    
    @pyqtSlot(str, str)
    def handle_detection(self, class_name, image_path):
        self.detection_count += 1
        self.log(f"🚨 ALERT #{self.detection_count}: Detected {class_name}!")
        self.status_bar.showMessage(f"Detection #{self.detection_count} | Type: {class_name}")

    def start_detection(self):
        # Case 1: Resume from Pause
        if hasattr(self, 'thread') and self.thread and self.thread.paused:
            self.thread.pause() # Toggle back to running
            self.log("⏯️ Detection Resumed.")
            self.update_control_buttons("RUNNING")
            return

        # Case 2: Start Fresh
        self.log("⏳ Initializing AI Model... (Please wait)")
        self.status_bar.showMessage("⏳ Loading AI Model...")
        QApplication.processEvents() # Cập nhật UI ngay lập tức để không cảm giác bị treo

        idx = self.combo_model.currentIndex()
        if idx == 0: model_path = 'model/small/best.pt'
        elif idx == 1: model_path = 'model/medium/best.pt'
        elif idx == 2: model_path = 'model/medium/mediumv2.pt'
        elif idx == 3: model_path = 'model/medium/mediumv3.pt'
        else: model_path = 'model/small/best.pt'
        
        # SWITCH BACK TO LIVE VIEW (Page 0)
        self.stack_video.setCurrentIndex(0)
        
        if self.source == 0: self.log("Starting Webcam...")
        else: self.log(f"Processing File: {self.source}")
        
        conf_threshold = self.slider_conf.value() / 100.0
        
        # Load fresh every time (Old behavior)
        self.thread = DetectionThread(model_path=model_path, source=self.source, save_path=self.output_path, conf_threshold=conf_threshold)
        self.thread.change_pixmap_signal.connect(self.update_image)
        self.thread.detection_signal.connect(self.handle_detection)
        self.thread.snapshot_saved.connect(self.display_snapshots) 
        self.thread.finished.connect(self.on_process_finished) 
        self.thread.start()
        
        self.update_control_buttons("RUNNING")
        
    def cancel_detection(self):
        """Handle Stop/Pause/Cancel Logic"""
        if not hasattr(self, 'thread') or not self.thread: return
        
        # Case 1: Currently Running -> PAUSE
        if not self.thread.paused:
            self.thread.pause()
            self.log("⏸️ Detection Paused.")
            self.update_control_buttons("PAUSED")
            
        # Case 2: Already Paused -> CANCEL (Reset)
        else:
            self.log("❌ Cancelling detection session...")
            self.thread.stop()
            self.thread = None
            
            # Reset UI
            self.update_control_buttons("IDLE")
            self.status_bar.showMessage("Session Cancelled")
            
            # Refund/Reset State
            self.snapshot_paths = [None, None, None]
            self.img_before.setText("No Image")
            self.img_before.setPixmap(QPixmap())
            self.img_during.setText("No Image")
            self.img_during.setPixmap(QPixmap())
            self.img_after.setText("No Image")
            self.img_after.setPixmap(QPixmap())
            
            self.stack_video.setCurrentIndex(0)
            if self.source == 0:
                self.image_label.setText("📹 No Video Feed")
                self.image_label.setStyleSheet("background: #1a1a1a; border: 2px solid #444; border-radius: 8px;")
            else:
                 self.image_label.setText(f"🎬 Ready to Play: {os.path.basename(str(self.source)) if self.source else ''}\nClick 'Start Detection' to begin")
            
            self.log("🔄 Session reset. Ready for new detection.")

    def update_control_buttons(self, state):
        """Update button text/state based on app state: IDLE, RUNNING, PAUSED"""
        if state == "IDLE":
            self.btn_start.setText("▶️ Start Detection")
            self.btn_start.setEnabled(True)
            self.btn_select.setEnabled(True)
            
            self.btn_cancel.setText("❌ Cancel Detection")
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold;")
            
        elif state == "RUNNING":
            self.btn_start.setText("▶️ Start Detection")
            self.btn_start.setEnabled(False) 
            self.btn_select.setEnabled(False)
            
            self.btn_cancel.setText("⏸️ Pause Detection")
            self.btn_cancel.setEnabled(True)
            self.btn_cancel.setStyleSheet("background-color: #f59e0b; color: white; font-weight: bold;") # Amber for pause
            
        elif state == "PAUSED":
            self.btn_start.setText("⏯️ Resume Detection")
            self.btn_start.setEnabled(True)
            self.btn_select.setEnabled(False)
            
            self.btn_cancel.setText("❌ Cancel Session")
            self.btn_cancel.setEnabled(True)
            self.btn_cancel.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold;") # Red for cancel
        
    
    def toggle_theme(self):
        """Switch between dark and light theme"""
        if self.is_dark_mode:
            self.setStyleSheet(self.get_light_theme())
            self.is_dark_mode = False
            self.log("💡 Switched to Light Theme")
        else:
            self.setStyleSheet(self.get_dark_theme())
            self.is_dark_mode = True
            self.log("🌙 Switched to Dark Theme")

    def select_analyst_video(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Video Files (*.mp4 *.avi *.mkv)")
        if file:
            self.analyst_file_path = file
            self.lbl_selected_file.setText(f"📄 {os.path.basename(file)}")
            self.btn_analyze.setEnabled(True)
            self.lbl_status_analyst.setText("Ready to process.")
            
            # SHOW RAW VIDEO
            self.analyst_stack.setCurrentIndex(1) # Page 1 is Player Container
            self.analyst_snapshot_group.hide() # Ensure results are hidden
            
            # Use VideoPlayerWidget to replay raw video
            self.show_analyst_player(file)

    def show_analyst_player(self, video_path):
        from widgets.video_player import VideoPlayerWidget
        # Clear previous player but KEEP loading container
        for i in range(self.analyst_player_layout.count()):
            item = self.analyst_player_layout.itemAt(i)
            widget = item.widget()
            if widget and widget != self.analyst_loading_container:
                widget.deleteLater()
            
        player = VideoPlayerWidget(video_path)
        self.analyst_player_layout.addWidget(player)

    def get_light_theme(self):
        """Modern light theme stylesheet"""
        return """
        QMainWindow {
            background-color: #f5f5f5;
        }
        QWidget {
            background-color: #ffffff;
            color: #333333;
            font-family: 'Segoe UI', Arial;
            font-size: 13px;
        }
        QTabWidget::pane {
            border: 1px solid #ccc;
            background: #ffffff;
        }
        QTabBar::tab {
            background: #e0e0e0;
            color: #555;
            padding: 10px 20px;
            border: 1px solid #ccc;
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }
        QTabBar::tab:selected {
            background: #ffffff;
            color: #2563eb;
            font-weight: bold;
            border-bottom: 2px solid #2563eb;
        }
        QGroupBox {
            border: 1px solid #ccc;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 15px;
            font-weight: bold;
            color: #2563eb;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
            background-color: #ffffff; /* Mask border behind title */
        }
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 #ffffff, stop:1 #f0f0f0);
            border: 1px solid #ccc;
            border-radius: 6px;
            padding: 8px;
            color: #333;
            font-weight: 600;
        }
        QPushButton:hover {
            background: #e0f2fe;
            border: 1px solid #3b82f6;
            color: #1d4ed8;
        }
        QPushButton:pressed {
            background: #dbeafe;
        }
        QPushButton:disabled {
            background: #f5f5f5;
            color: #aaa;
            border: 1px solid #ddd;
        }
        QComboBox {
            background: #ffffff;
            border: 1px solid #ccc;
            border-radius: 4px;
            padding: 6px;
            color: #333;
        }
        QComboBox:hover {
            border: 1px solid #3b82f6;
        }
        QSlider::groove:horizontal {
            border: 1px solid #ccc;
            height: 6px;
            background: #e0e0e0;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #3b82f6;
            border: 1px solid #2563eb;
            width: 16px;
            margin: -6px 0;
            border-radius: 8px;
        }
        QTextEdit, QLabel {
            background: #ffffff;
            border: 1px solid #ccc;
            border-radius: 4px;
            padding: 4px;
            color: #333;
        }
        QStatusBar {
            background: #f5f5f5;
            color: #555;
            border-top: 1px solid #ddd;
        }
        /* Special overrides for Image Containers to stay dark/neutral */
        QLabel[text="📹 No Video Feed"], QLabel[text="No Image"] {
            background-color: #000000;
            color: #ffffff;
            border: 2px solid #555;
        }
        
        /* Analyst Tab Specifics - Light */
        QWidget#analystRightPanelWrapper, QWidget#analystRightPanel {
            background-color: #ffffff;
            border-left: 1px solid #ccc;
        }
        QLabel#lblSelectedFile {
            color: #555;
            font-style: italic;
        }
        QLabel#lblAnalystStatus {
             color: #555;
        }
        QLabel#lblAnalystPreview {
             background-color: #f3f4f6;
             border: 1px dashed #ccc;
             color: #888;
        }
        """

    def get_dark_theme(self):
        """Modern dark theme stylesheet"""
        return """
        QMainWindow {
            background-color: #1e1e1e;
        }
        QWidget {
            background-color: #2b2b2b;
            color: #e0e0e0;
            font-family: 'Segoe UI', Arial;
            font-size: 13px;
        }
        
        /* Analyst Tab Specifics - Dark */
        QWidget#analystRightPanelWrapper, QWidget#analystRightPanel {
            background-color: #2b2b2b;
            border-left: 1px solid #444;
        }
        QLabel#lblSelectedFile {
            color: #aaa;
            font-style: italic;
        }
        QLabel#lblAnalystStatus {
             color: #ccc;
        }
        QLabel#lblAnalystPreview {
             background-color: #000;
             border: 1px dashed #555;
             color: #555;
        }
        
        QTabWidget::pane {
            border: 1px solid #444;
            background: #2b2b2b;
        }
        QTabBar::tab {
            background: #3a3a3a;
            color: #ccc;
            padding: 10px 20px;
            border: 1px solid #444;
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }
        QTabBar::tab:selected {
            background: #2b2b2b;
            color: #3b82f6;
            font-weight: bold;
        }
        QGroupBox {
            border: 2px solid #444;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 15px;
            font-weight: bold;
            color: #3b82f6;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 #4a4a4a, stop:1 #3a3a3a);
            border: 1px solid #555;
            border-radius: 6px;
            padding: 8px;
            color: #e0e0e0;
            font-weight: 600;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 #5a5a5a, stop:1 #4a4a4a);
            border: 1px solid #3b82f6;
        }
        QPushButton:pressed {
            background: #2a2a2a;
        }
        QPushButton:disabled {
            background: #2a2a2a;
            color: #666;
        }
        QComboBox {
            background: #3a3a3a;
            border: 1px solid #555;
            border-radius: 4px;
            padding: 6px;
            color: #e0e0e0;
        }
        QComboBox:hover {
            border: 1px solid #3b82f6;
        }
        QComboBox::drop-down {
            border: none;
            width: 20px;
        }
        QSlider::groove:horizontal {
            border: 1px solid #555;
            height: 6px;
            background: #3a3a3a;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #3b82f6;
            border: 1px solid #2563eb;
            width: 16px;
            margin: -6px 0;
            border-radius: 8px;
        }
        QSlider::handle:horizontal:hover {
            background: #60a5fa;
        }
        QTextEdit, QLabel {
            background: #2b2b2b;
            border: 1px solid #444;
            border-radius: 4px;
            padding: 4px;
            color: #e0e0e0;
        }
        QStatusBar {
            background: #1e1e1e;
            color: #888;
            border-top: 1px solid #444;
        }
        """

    @pyqtSlot(np.ndarray)
    def update_image(self, cv_img):
        qt_img = self.convert_cv_qt(cv_img)
        self.image_label.setPixmap(qt_img)
    
    @pyqtSlot(str, str, str)
    def display_snapshots(self, path_before, path_during, path_after):
        """Display the 3 captured snapshots in gallery"""
        self.log(f"📸 Snapshots captured!")
        
        # Store paths for zoom functionality
        self.snapshot_paths = [path_before, path_during, path_after]
        
        # Load and display each image
        for path, label in [
            (path_before, self.img_before),
            (path_during, self.img_during),
            (path_after, self.img_after)
        ]:
            if path and os.path.exists(path):
                pixmap = QPixmap(path)
                label.setPixmap(pixmap)
                label.setText("")  # Clear placeholder text
            else:
                label.setText("Error")
                self.log(f"⚠️ Image not found: {path}")
        
        # Enable Manual Report Button now that we have images
        self.btn_manual_report.setEnabled(True)
        
        # DEFERRED: Do not generate report immediately. Wait for on_process_finished.
        # This prevents spamming reports if multiple detections occur or if the first one is bad.
        self.log("📸 Snapshots captured. Waiting for process completion to report.")

    def show_full_image(self, index):
        """Show full size image in a lightbox dialog"""
        if not hasattr(self, 'snapshot_paths') or index >= len(self.snapshot_paths):
            return
            
        path = self.snapshot_paths[index]
        if not path or not os.path.exists(path):
            self.log("⚠️ No image to zoom")
            return
            
        # Create Lightbox Dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"🔍 Full View - {['Before', 'During', 'After'][index]}")
        dialog.setStyleSheet("background: #000;")
        
        # Maximize but leave margins
        screen = QApplication.primaryScreen().availableGeometry()
        dialog.resize(int(screen.width() * 0.9), int(screen.height() * 0.9))
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Image Label
        label = QLabel()
        pixmap = QPixmap(path)
        
        # Scale pixmap to fit dialog initially
        scaled_pixmap = pixmap.scaled(dialog.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(scaled_pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(label)
        
        # Click to close
        label.mousePressEvent = lambda e: dialog.close()
        
        dialog.exec()

    def update_conf_label(self, value):
        self.lbl_conf.setText(f"⚙️ Confidence: {value / 100.0:.2f}")

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
        """Ensure proper cleanup when closing window"""
        print("🚪 closeEvent triggered")
        self.cleanup()
        event.accept()

        import os
        print("☠️ Force killing process...")
        os._exit(0) # Giết tiến trình ngay lập tức, bỏ qua mọi chờ đợi
    
    def cleanup(self):
        """Centralized cleanup method"""
        # Prevent recursive calls
        if hasattr(self, '_cleanup_in_progress') and self._cleanup_in_progress:
            return
        
        self._cleanup_in_progress = True
        print("🛑 Starting cleanup...")
        
        if self.thread and self.thread.isRunning():
            print("⏸️ Stopping detection thread...")
            self.thread.stop()
            
            # Wait for thread to finish (with timeout)
            print("⏳ Waiting for thread to stop (max 2s)...")
            if not self.thread.wait(2000):  # 2s timeout
                print("⚠️ Thread didn't stop, force terminating...")
                self.thread.terminate()
                if not self.thread.wait(1000):  # 1s for termination
                    print("❌ Force quit failed!")
                else:
                    print("✅ Thread force-terminated")
            else:
                print("✅ Thread stopped gracefully")
        
        # Release CV2 resources
        try:
            cv2.destroyAllWindows()
            print("✅ CV2 windows destroyed")
        except:
            pass
        
        # Close any open resources
        if hasattr(self, 'api_client'):
            self.api_client = None
        
        print("✅ Cleanup complete")
    
    def __del__(self):
        """Destructor - last resort cleanup"""
        try:
            if hasattr(self, 'thread') and self.thread and self.thread.isRunning():
                print("⚠️ __del__ cleanup - thread still running!")
                self.thread.terminate()
                self.thread.wait()
        except:
            pass

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    print("\n🛑 Interrupt received, forcing exit...")
    import sys
    sys.exit(0)

if __name__ == "__main__":
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)  # Ensure quit when window closes
    
    window = TrafficMonitorApp()
    
    # Cleanup before quit
    app.aboutToQuit.connect(window.cleanup)
    
    window.show()
    
    # Use exec() and ensure exit
    exit_code = app.exec()
    print(f"📤 Application exiting with code: {exit_code}")
    
    # Force cleanup one more time
    window.cleanup()
    
    # Force exit
    import sys
    sys.exit(exit_code)
