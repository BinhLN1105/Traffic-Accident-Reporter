import cv2
import time
import os
from collections import deque
from PyQt6.QtCore import QThread, pyqtSignal
from ultralytics import YOLO
import numpy as np

# Thiết lập thư mục gốc để lưu dữ liệu
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

class DetectionThread(QThread):
    """
    Thread xử lý phát hiện sự cố giao thông bằng YOLO
    Chạy trong background để không làm đơ UI
    """
    change_pixmap_signal = pyqtSignal(np.ndarray)  # Signal phát frame đã vẽ để hiển thị
    detection_signal = pyqtSignal(str, str)  # Signal phát khi phát hiện sự cố (label, image_path)
    snapshot_saved = pyqtSignal(str, str, str)  # Signal phát 3 đường dẫn ảnh (trước, trong, sau)
    process_finished_signal = pyqtSignal(dict)  # Signal phát khi hoàn thành xử lý (cho chế độ analyst)
    progress_signal = pyqtSignal(int)  # Signal phát tiến độ xử lý (phần trăm)

    def __init__(self, model_path='best.pt', source=0, save_path=None, custom_labels="accident, vehicle accident", conf_threshold=0.70, loop=True):
        """
        Khởi tạo thread phát hiện
        
        Args:
            model_path: Đường dẫn đến file mô hình YOLO
            source: Nguồn video (0 = webcam, hoặc đường dẫn file)
            save_path: Đường dẫn lưu video đã xử lý (None = không lưu)
            custom_labels: Các nhãn cần phát hiện, phân cách bởi dấu phẩy
            conf_threshold: Ngưỡng độ tin cậy (0.0 - 1.0)
            loop: Có lặp lại video không (True = lặp, False = chạy một lần)
        """
        super().__init__()
        self.model_path = model_path
        self.source = source
        self.save_path = save_path
        self.custom_labels = custom_labels
        self.conf_threshold = conf_threshold
        self.loop = loop  # Điều khiển hành vi lặp lại
        self.model = None
        self.running = True
        self.paused = False
        self.out = None

    def pause(self):
        """
        Chuyển đổi giữa tạm dừng và tiếp tục
        Trả về trạng thái mới (True = đang tạm dừng)
        """
        self.paused = not self.paused
        return self.paused

    def run(self):
        """
        Hàm chính chạy trong thread
        Xử lý video frame-by-frame, phát hiện sự cố và chụp ảnh
        """
        # Phân tích các nhãn cần phát hiện từ chuỗi custom_labels
        target_labels = [l.strip().lower() for l in self.custom_labels.split(',') if l.strip()]
        
        # 1. Tải mô hình YOLO
        try:
            print(f"Loading model from {self.model_path}...")
            self.model = YOLO(self.model_path)
        except Exception as e:
            print(f"Error loading model: {e}")
            return

        # 2. Mở nguồn video (webcam hoặc file)
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            print("Cannot open video source")
            return

        # --- CẤU HÌNH THỜI GIAN ĐỘNG ---
        # Lấy thông tin FPS và tổng số frame của video
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # Nếu không có FPS hoặc FPS = 0, dùng giá trị mặc định
        if video_fps == 0 or np.isnan(video_fps): 
            video_fps = 30  # Giá trị dự phòng
        
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # --- Tính toán kích thước resize trước ---
        # Giảm kích thước frame lớn để tăng tốc độ xử lý
        target_width = width
        target_height = height
        if width > 640:
            scale = 640 / width
            target_width = 640
            target_height = int(height * scale)

        # Thiết lập Video Writer để lưu video đã xử lý
        if self.save_path:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.out = cv2.VideoWriter(self.save_path, fourcc, video_fps, (target_width, target_height))
        
        # Cấu hình thời gian chụp ảnh (khớp với server.py)
        BEFORE_SECONDS = 4.0  # Chụp ảnh "trước" cách 4 giây
        AFTER_SECONDS = 5.0   # Chụp ảnh "sau" cách 5 giây
        
        # Tính toán kích thước buffer và số frame cần thiết
        BUFFER_SIZE = int(video_fps * BEFORE_SECONDS)  # Buffer chứa 4 giây frame
        AFTER_FRAMES_REQUIRED = int(video_fps * AFTER_SECONDS)  # Số frame cần đợi để chụp "sau"
        
        SKIP_FRAMES = 3  # Xử lý mỗi frame thứ 3 để tăng tốc (khớp với server)

        
        # Buffer lưu trữ các frame gần đây (dùng deque để tự động xóa frame cũ)
        frame_buffer = deque(maxlen=BUFFER_SIZE)
        
        # Các biến trạng thái
        snapshot_state = "IDLE"  # Trạng thái: IDLE, WAITING_FOR_AFTER
        frames_since_incident = 0  # Số frame đã trôi qua kể từ khi phát hiện sự cố
        current_incident_label = ""  # Nhãn của sự cố hiện tại
        current_sequence_id = 0  # ID của chuỗi ảnh chụp hiện tại
        last_alert_time = 0  # Thời gian cảnh báo cuối cùng
        alert_cooldown = 30  # Thời gian chờ giữa các cảnh báo (giây)
        current_accident_streak = 0  # Đếm số frame liên tiếp phát hiện sự cố
        
        # Theo dõi dự phòng (fallback) - lưu phát hiện tốt nhất nếu không có sự cố kéo dài
        best_fallback_conf = 0.0  # Độ tin cậy tốt nhất
        best_fallback_data = None  # (label, frame_before, frame_during)
        
        frame_count = 0  # Đếm số frame đã xử lý
        last_boxes = []  # Lưu kết quả detection của frame trước để tái sử dụng
        
        # Logic chống nhấp nháy (Anti-Flicker)
        # Cho phép một số frame không phát hiện mà không reset streak
        missing_frame_tolerance_count = 0
        MAX_MISSING_FRAMES = 5  # Cho phép 5 frame (khoảng 0.15s) không phát hiện
        
        # Lưu frame khi sự cố bắt đầu
        potential_incident_frame = None
        
        # Theo dõi sự cố cuối cùng để tạo báo cáo cuối
        final_snapshots = []
        final_incident_id = None

        print(f"Video Info: FPS={video_fps}, Buffer Size={BUFFER_SIZE}, After Frames={AFTER_FRAMES_REQUIRED}")

        # 3. VÒNG LẶP CHÍNH
        self.running = True
        while self.running and cap.isOpened():
            # --- LOGIC TẠM DỪNG ---
            if self.paused:
                time.sleep(0.1)  # Ngủ để tiết kiệm CPU
                continue
                
            # --- LOGIC LẶP LẠI & ĐỌC FRAME ---
            ret, frame = cap.read()
            
            # Tự động lặp lại nếu video kết thúc VÀ chế độ lặp BẬT
            if not ret:
                if self.loop:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
                    if not ret: break 
                else:
                    # Chế độ không lặp: Chỉ dừng lại
                    print("End of video stream (No Loop).")
                    break
            
            # --- TỐI ƯU HÓA (Resize để tăng tốc) ---
            # Giảm kích thước frame lớn xuống tối đa 640px chiều rộng để cải thiện FPS
            h, w = frame.shape[:2]
            if w > 640:
                scale = 640 / w
                new_w, new_h = 640, int(h * scale)
                frame = cv2.resize(frame, (new_w, new_h))

            last_valid_frame = frame.copy()  # Lưu frame hợp lệ cuối cùng
            frame_buffer.append(frame.copy())  # Thêm vào buffer
            frame_count += 1
            annotated_frame = frame.copy()  # Frame để vẽ annotation
            
            # Phát signal tiến độ (việc lặp làm phức tạp, nhưng có thể wrap)
            if total_frames > 0:
                # Wrap tiến độ 0-100% mỗi lần lặp
                current_loop_frame = frame_count % total_frames
                progress = int((current_loop_frame / total_frames) * 100)
                self.progress_signal.emit(progress)

            # --- A. PHÁT HIỆN ---
            # Logic bỏ qua frame (Server dùng % 3)
            if frame_count % 3 == 0:
                # Chạy YOLO để phát hiện và theo dõi đối tượng
                results = self.model.track(frame, persist=True, verbose=False, conf=self.conf_threshold)

                
                last_boxes = []  # Reset danh sách box để lưu kết quả mới
                
                current_time = time.time()
                is_incident_now = False
                detected_label = ""

                # Duyệt qua tất cả kết quả phát hiện
                for result in results:
                    for box in result.boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])  # Tọa độ bounding box
                        cls_id = int(box.cls[0])  # ID lớp
                        label = self.model.names[cls_id]  # Tên lớp
                        conf = float(box.conf[0])  # Độ tin cậy
                        
                        last_boxes.append((x1, y1, x2, y2, label, conf))
                        
                        # Kiểm tra xem label có trong danh sách cần phát hiện không
                        if label.lower() in target_labels:
                            detected_label = label
                            
                            # Cập nhật ứng viên dự phòng (độ tin cậy tốt nhất)
                            # Dùng khi không có sự cố kéo dài nhưng có phát hiện tốt
                            if conf > best_fallback_conf:
                                best_fallback_conf = conf
                                fb_before = frame_buffer[0].copy() if frame_buffer else frame.copy()
                                fb_during = frame.copy()
                                best_fallback_data = (label, fb_before, fb_during)

                # --- LOGIC XÁC NHẬN (Kiểm tra độ bền vững) ---
                # Cần phát hiện liên tiếp trong một khoảng thời gian để xác nhận sự cố
                ACCIDENT_DURATION_THRESHOLD = 0.5  # Cần 0.5 giây để xác thực
                CONFIRMATION_FRAMES = int(video_fps * ACCIDENT_DURATION_THRESHOLD)
                
                if detected_label:
                    # Có phát hiện sự cố trong frame này
                    current_accident_streak += 1  # Tăng streak
                    missing_frame_tolerance_count = 0  # Reset tolerance khi phát hiện
                    
                    # Chụp khoảnh khắc chính xác khi sự cố BẮT ĐẦU (Streak == 1)
                    if current_accident_streak == 1:
                        # BÙ ĐẮP CHO ĐỘ TRỄ CỦA AI
                        # AI phát hiện mất vài frame, người dùng cảm thấy nó "muộn"
                        # Lấy frame từ ~0.3 giây TRƯỚC từ buffer để lấy "Khoảnh khắc va chạm"
                        rewind_frames = int(video_fps * 0.3)  # Tua ngược 0.3 giây
                        if len(frame_buffer) > rewind_frames:
                            potential_incident_frame = frame_buffer[-rewind_frames].copy()
                        elif frame_buffer:
                            potential_incident_frame = frame_buffer[0].copy()
                        else:
                            potential_incident_frame = frame.copy()
                        
                else:
                    # KHÔNG có phát hiện trong frame này
                    # CHỐNG NHẤP NHÁY: Không reset ngay lập tức
                    if current_accident_streak > 0 and missing_frame_tolerance_count < MAX_MISSING_FRAMES:
                        missing_frame_tolerance_count += 1
                        # Duy trì streak (không tăng, không reset)
                    else:
                        # Reset streak nếu đã vượt quá tolerance
                        current_accident_streak = 0
                        potential_incident_frame = None
                        missing_frame_tolerance_count = 0

                # --- KÍCH HOẠT SỰ KIỆN ---
                # Điều kiện để bắt đầu chụp ảnh:
                # 1. Đang ở trạng thái IDLE (chưa chụp)
                # 2. Đã qua thời gian cooldown giữa các cảnh báo
                # 3. Streak đã đạt ngưỡng xác nhận
                if snapshot_state == "IDLE" and \
                   (current_time - last_alert_time > alert_cooldown) and \
                   current_accident_streak >= CONFIRMATION_FRAMES:
                    
                    is_incident_now = True
                    
                    # Logic tua ngược để lấy frame "During" tốt hơn
                    SECONDS_TO_REWIND = 1.0  # Tua ngược 1 giây
                    frames_back = int(video_fps * SECONDS_TO_REWIND)
                    
                    # Lấy frame từ buffer (ưu tiên frame cũ hơn để bắt khoảnh khắc va chạm)
                    if len(frame_buffer) > frames_back:
                        snap_frame = frame_buffer[-frames_back].copy()  # Lấy ảnh từ 1 giây trước
                        print(f"📸 Captured frame from {SECONDS_TO_REWIND}s ago!")
                    elif frame_buffer:
                        snap_frame = frame_buffer[0].copy()  # Lấy ảnh cũ nhất có thể
                    else:
                        snap_frame = frame.copy()  # Bất đắc dĩ mới lấy ảnh hiện tại

                    # Cập nhật các biến trạng thái
                    last_alert_time = current_time
                    current_sequence_id = int(time.time())  # ID duy nhất cho chuỗi ảnh này
                    final_incident_id = current_sequence_id
                    current_incident_label = detected_label
                    frames_since_incident = 0

                    # --- LƯU ẢNH ---
                    if self.loop:
                         # Chế độ Live: Lưu Before và During ngay
                         # 1. Before: Lấy từ đầu buffer (frame cũ nhất)
                         frame_before = frame_buffer[0] if frame_buffer else frame
                         path_before = self.save_image(frame_before, current_sequence_id, detected_label, "1_before")

                         # 2. During: Lưu frame đã tua ngược (khoảnh khắc va chạm)
                         path_during = self.save_image(snap_frame, current_sequence_id, detected_label, "2_during")
                        
                         current_snapshot_paths = [path_before, path_during, None]
                         final_snapshots = current_snapshot_paths
                        
                         # Phát signal để UI cập nhật
                         self.snapshot_saved.emit(*current_snapshot_paths)
                        
                         snapshot_state = "WAITING_FOR_AFTER"  # Chuyển sang chờ ảnh "After"
                        
                    else:
                        # Chế độ Analyst (không lặp)
                        snapshot_state = "WAITING_FOR_AFTER"
                        
                        # 1. Before: Lấy ảnh cũ nhất trong buffer (cách đây 4s)
                        frame_before = frame_buffer[0] if frame_buffer else frame
                        path_before = self.save_image(frame_before, current_sequence_id, detected_label, "1_before")
                        
                        # 2. During: Lấy frame đã tua ngược
                        path_during = self.save_image(snap_frame, current_sequence_id, detected_label, "2_during")
                        
                        current_snapshot_paths = [path_before, path_during, None]
                        final_snapshots = current_snapshot_paths 
                        
                        # Phát signal phát hiện
                        self.detection_signal.emit(detected_label, path_during)

            # --- B. VẼ BOXES & TIMESTAMP ---
            # Thêm timestamp vào frame (theo style của server)
            time_str = str(time.strftime("%H:%M:%S", time.gmtime(frame_count / video_fps)))
            # Vẽ outline đen trước, sau đó vẽ text vàng để dễ đọc
            cv2.putText(annotated_frame, f"Time: {time_str}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
            cv2.putText(annotated_frame, f"Time: {time_str}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            # Vẽ các bounding box và nhãn
            for (x1, y1, x2, y2, label, conf) in last_boxes:
                # Màu đỏ cho sự cố, màu xanh cho đối tượng khác
                color = (0, 0, 255) if label.lower() in target_labels else (0, 255, 0)
                # Vẽ hình chữ nhật
                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                
                # Vẽ nhãn với nền
                text = f"{label} {conf:.2f}"
                (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                cv2.rectangle(annotated_frame, (x1, y1 - 20), (x1 + w, y1), color, -1)
                cv2.putText(annotated_frame, text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            
            # --- THANH DEBUG ---
            # Hiển thị thanh tiến độ xác nhận khi đang xác nhận sự cố
            if current_accident_streak > 0 and snapshot_state == "IDLE":
                bar_width = min(int((current_accident_streak / CONFIRMATION_FRAMES) * 100), 100)
                cv2.rectangle(annotated_frame, (10, 10), (10 + bar_width, 20), (0, 0, 255), -1)

            # --- C. CẬP NHẬT STATE MACHINE ---
            # Xử lý logic chờ chụp ảnh "After"
            if snapshot_state == "WAITING_FOR_AFTER":
                frames_since_incident += 1
                if frames_since_incident >= AFTER_FRAMES_REQUIRED:
                    # 3. Lưu ảnh AFTER (sau khi đã đợi đủ số frame)
                    path_after = self.save_image(frame, current_sequence_id, current_incident_label, "3_after")
                    print("Sequence capture complete.")
                    
                    if 'current_snapshot_paths' in locals():
                        current_snapshot_paths[2] = path_after
                        self.snapshot_saved.emit(*current_snapshot_paths)
                        final_snapshots = current_snapshot_paths 

                    snapshot_state = "IDLE"  # Quay về trạng thái chờ

            # --- D. ĐẦU RA ---
            # Phát frame đã vẽ để UI hiển thị
            self.change_pixmap_signal.emit(annotated_frame)
            # Ghi vào video nếu có
            if self.out:
                self.out.write(annotated_frame)

        # Dọn dẹp
        print("Stopping detection thread...")
        cap.release()
        if self.out:
            self.out.release()
            
        # BẮT BUỘC HOÀN THÀNH SNAPSHOT NẾU ĐANG CHỜ
        # Nếu video kết thúc trước khi chụp được ảnh "After"
        if snapshot_state == "WAITING_FOR_AFTER" and 'current_snapshot_paths' in locals():
            print("Video ended before 'After' frame. Saving last frame as 'After'.")
            frame_after = last_valid_frame if last_valid_frame is not None else frame
            if frame_after is not None:
                path_after = self.save_image(frame_after, current_sequence_id, current_incident_label, "3_after")
                current_snapshot_paths[2] = path_after
                final_snapshots = current_snapshot_paths
        
        # --- LOGIC DỰ PHÒNG MỚI ---
        # Nếu không có snapshot nào được tạo, nhưng có phát hiện gì đó
        # Dùng dữ liệu dự phòng tốt nhất để tạo snapshot
        if not final_snapshots and best_fallback_data is not None:
            print(f"⚠️ No prolonged incident confirmed. Using FALLBACK snapshot (Best Conf: {best_fallback_conf:.2f})")
            fb_label, fb_before, fb_during = best_fallback_data
            fb_seq_id = int(time.time())
            
            p1 = self.save_image(fb_before, fb_seq_id, fb_label, "1_before")
            p2 = self.save_image(fb_during, fb_seq_id, fb_label, "2_during")
            # Dùng frame cuối làm 'After'
            last_frame = last_valid_frame if last_valid_frame is not None else fb_during
            p3 = self.save_image(last_frame, fb_seq_id, fb_label, "3_after")
            
            final_snapshots = [p1, p2, p3]
            final_incident_id = fb_seq_id
            
            # Phát signal để UI cập nhật
            self.detection_signal.emit(fb_label, p2)

        
        # Phát signal hoàn thành (cho chế độ analyst)
        self.process_finished_signal.emit({
            'success': True,
            'output_path': self.save_path,
            'snapshots': final_snapshots,
            'incident_id': str(final_incident_id) if final_incident_id else str(int(time.time()))
        })
            
    def stop(self):
        """
        Gửi tín hiệu dừng thread và đợi nó kết thúc
        """
        self.running = False
        self.wait()

    def save_image(self, frame, seq_id, label, suffix):
        """
        Lưu ảnh vào thư mục data
        
        Args:
            frame: Frame cần lưu
            seq_id: ID của chuỗi ảnh
            label: Nhãn của sự cố
            suffix: Hậu tố (1_before, 2_during, 3_after)
        
        Returns:
            Đường dẫn file đã lưu
        """
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        
        filename = f"{seq_id}_{label}_{suffix}.jpg"
        filepath = os.path.join(DATA_DIR, filename)
        cv2.imwrite(filepath, frame)
        return filepath