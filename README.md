# 🚦 Traffic Accident AI Reporter

> **Hệ Thống Giám Sát Tai Nạn Giao Thông Thế Hệ Mới, được hỗ trợ bởi YOLOv8 và Google Gemini AI**

![Project Status](https://img.shields.io/badge/Status-Active-success?style=flat-square)
![Java](https://img.shields.io/badge/Backend-Spring%20Boot-green?style=flat-square&logo=springboot)
![Python](https://img.shields.io/badge/AI%20Core-Python%20%7C%20YOLOv8-blue?style=flat-square&logo=python)
![AI](https://img.shields.io/badge/Intelligence-Google%20Gemini-orange?style=flat-square&logo=google)
![WebRTC](https://img.shields.io/badge/Streaming-WebRTC-red?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square)

---

## 📖 Tổng Quan

**Traffic Accident Reporter** là một hệ thống giám sát giao thông thông minh, kết hợp **AI phân tích real-time** và **phát hiện sự cố tự động**. Hệ thống sử dụng **YOLOv8** cho thị giác máy tính và **Google Gemini AI** để tạo báo cáo chi tiết về tai nạn giao thông.

### 🎯 Điểm Nổi Bật

- ✅ **Dual Mode**: Hỗ trợ cả phân tích video offline (Batch) và streaming real-time (Live)
- ✅ **WebRTC Streaming**: Truyền video trực tiếp với độ trễ thấp
- ✅ **AI-Powered Reports**: Báo cáo được tạo tự động bởi Gemini AI
- ✅ **Multi-Platform**: Web Dashboard + Desktop GUI (PyQt6)
- ✅ **Smart Detection**: Snapshot Before/During/After incident
- ✅ **Production Ready**: Fallback mechanism, error handling, resource cleanup

---

## ✨ Tính Năng

### 📹 Chế Độ Phân Tích

#### 1. **Batch Mode** (Video Analysis)
- Upload video từ camera giao thông
- Phát hiện tai nạn tự động với YOLOv8
- Tạo báo cáo AI chi tiết (mức độ nghiêm trọng, nguyên nhân, đề xuất)
- Lưu trữ lịch sử sự cố vào database

#### 2. **Live Stream Mode** (Real-time)
- Streaming WebRTC với độ trễ thấp (<1s)
- Phát hiện tai nạn trong thời gian thực
- Snapshot tự động khi phát hiện sự cố
- Tạo báo cáo AI cho session stream

### 🧠 AI & Machine Learning

- **YOLOv8 Object Detection**: 
  - 2 model sizes: Small (Fast) và Medium V1 (Balanced)
  - Confidence threshold điều chỉnh được
  - Multi-label detection

- **Google Gemini AI Analysis**:
  - Phân tích cảnh tai nạn từ snapshots
  - Tạo báo cáo structured (severity, cause, recommendations)
  - Fallback chain: Gemini 2.5 Flash → 1.5 Flash
  - Smart caching để tối ưu API usage

### 🖥️ Giao Diện Người Dùng

#### Web Dashboard
- Material Design với dark/light theme
- Video preview và playback
- Snapshot gallery
- Real-time progress tracking
- History management

#### Desktop Application (PyQt6)
- Full-featured GUI với video player
- Model configuration
- Report generation
- Incident history viewer

---

## 🏗️ Kiến Trúc Hệ Thống

```
┌─────────────────────────────────────────────────────────────┐
│                      USER INTERFACES                        │
│  ┌──────────────────┐         ┌──────────────────┐         │
│  │  Web Dashboard   │         │  Desktop App     │         │
│  │  (HTML/JS/CSS)   │         │  (PyQt6)         │         │
│  └────────┬─────────┘         └────────┬─────────┘         │
└───────────┼──────────────────────────┼─────────────────────┘
            │                          │
            ▼                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   JAVA BACKEND (Spring Boot)                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  • REST API Endpoints                                │  │
│  │  • Task Management (VideoProcessingManager)          │  │
│  │  • AI Integration (GeminiService)                    │  │
│  │  • Database Management (JPA/Hibernate)               │  │
│  │  • Report Generation                                 │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────┬──────────────────────────────────────────┘
                   │ HTTP API
                   ▼
┌─────────────────────────────────────────────────────────────┐
│              PYTHON AI SERVER (Flask + aiortc)              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  • YOLOv8 Detection Engine                           │  │
│  │  • WebRTC Streaming (aiortc)                         │  │
│  │  • Video Processing                                  │  │
│  │  • Snapshot Management                               │  │
│  │  • Frame Optimization (640px resize)                 │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                   │
                   ▼
         ┌──────────────────┐
         │  MySQL Database  │
         │  • Incidents      │
         │  • AI Reports     │
         │  • Media URLs     │
         └──────────────────┘
```

### Luồng Xử Lý

#### Batch Mode Flow
1. User uploads video → Java Backend
2. Java → Python (HTTP POST `/process`)
3. Python: YOLOv8 detection → Save snapshots
4. Python → Java: Status updates
5. Java: Gemini AI analysis → Database
6. User: View report & processed video

#### Live Stream Flow
1. User starts stream → Java Backend → Python
2. Python: WebRTC connection established
3. Video frames → YOLOv8 real-time detection
4. Incident detected → Save snapshots
5. User stops → Frontend syncs snapshots to Java
6. Java: Gemini AI analysis → Generate report

---

## 🚀 Cài Đặt & Chạy

### Yêu Cầu Hệ Thống

- **Java JDK 21+**
- **Python 3.10+**
- **Maven 3.8+**
- **MySQL 8.0+**
- **Node.js** (optional, for live-server)

### Bước 1: Clone Repository

```bash
git clone https://github.com/BinhLN1105/Traffic-Accident-Reporter.git
cd Traffic-Accident-Reporter
```

### Bước 2: Cấu Hình Database

1. Tạo MySQL database:
```sql
CREATE DATABASE traffic_incident_db;
```

2. Cập nhật `incident-reporter/src/main/resources/application.properties`:
```properties
spring.datasource.url=jdbc:mysql://localhost:3306/traffic_incident_db
spring.datasource.username=your_username
spring.datasource.password=your_password
```

### Bước 3: Cấu Hình Gemini API

Tạo file `incident-reporter/gemini-api-key.txt` và paste API key:
```
YOUR_GEMINI_API_KEY_HERE
```

> 🔑 Lấy API key tại: https://makersuite.google.com/app/apikey

### Bước 4: Setup Python AI Server

```bash
cd traffic-ai-client
pip install -r requirements.txt
python server.py
```

**Server sẽ chạy tại:** `http://localhost:5000`

### Bước 5: Chạy Java Backend

```bash
cd incident-reporter
mvn spring-boot:run
```

**Backend sẽ chạy tại:** `http://localhost:8080`

### Bước 6: Mở Web Dashboard

**Option 1: Direct file**
```bash
# Open in browser
cd traffic-frontend
open index.html
```

**Option 2: Live Server (recommended)**
```bash
npm install -g live-server
cd traffic-frontend
live-server
```

**Dashboard:** `http://localhost:5500` (or port shown by live-server)

### Bước 7 (Optional): Chạy Desktop App

```bash
cd traffic-ai-client
python main.py
```

---

## � Sử Dụng

### Web Dashboard

#### 1. Batch Analysis
1. Chọn tab **"Video Analyst"**
2. Click **"Choose File"** → chọn video
3. Cấu hình:
   - Model: Small (Fast) hoặc Medium (Balanced)
   - Confidence: 70% (recommended)
   - Auto-report: ON/OFF
4. Click **"⚡ Start Analysis"**
5. Xem kết quả: Processed video + AI Report

#### 2. Live Stream
1. Chọn tab **"Live"**
2. Upload video (sẽ được stream qua WebRTC)
3. Click **"▶️ Start Stream"**
4. Xem real-time detection
5. Click **"⏹️ Stop"** → **"📝 Create Live Report"**

### Desktop Application

1. **Live Detection Tab**: Webcam hoặc video file
2. **Analyst Tab**: Batch video analysis
3. **History Tab**: Xem lịch sử incidents từ database

---

## 🛠️ Tech Stack

### Backend
- **Java 21**
- **Spring Boot 3.4.1**
- **Spring Data JPA**
- **MySQL 8**
- **Lombok**
- **HikariCP**

### AI/ML Core
- **Python 3.10+**
- **YOLOv8** (Ultralytics)
- **OpenCV**
- **Google Generative AI SDK**
- **Flask** (REST API)
- **aiortc** (WebRTC)

### Frontend
- **Vanilla JavaScript (ES6+)**
- **HTML5 / CSS3**
- **WebRTC API**
- **Fetch API**

### Desktop App
- **PyQt6**
- **PyQt6-Multimedia**

---

## 📂 Cấu Trúc Dự Án

```
Traffic-Accident-Reporter/
├── incident-reporter/          # Java Spring Boot Backend
│   ├── src/main/java/com/traffic/incidentreporter/
│   │   ├── controller/        # REST API Endpoints
│   │   ├── service/          # Business Logic
│   │   ├── repository/       # Database Layer
│   │   └── entity/           # JPA Entities
│   └── src/main/resources/
│       └── application.properties
├── traffic-ai-client/         # Python AI Server
│   ├── server.py             # Flask + WebRTC Server
│   ├── main.py               # Desktop GUI App
│   ├── utils/                # Detection Thread
│   ├── widgets/              # UI Components
│   └── model/                # YOLO Models
│       ├── small/best.pt
│       └── medium/mediumv1.pt
├── traffic-frontend/          # Web Dashboard
│   ├── index.html            # Main UI
│   ├── app.js                # Application Logic
│   └── styles.css            # Styling
├── data/                      # Processed Videos & Snapshots
└── README.md
```

---

## ⚙️ Cấu Hình

### Lựa Chọn Model
- **Small**: Xử lý nhanh hơn, độ chính xác thấp hơn
- **Medium V1**: Cân bằng tốc độ/độ chính xác (khuyến nghị)

### Tham Số Phát Hiện
- **Ngưỡng Tin Cậy (Confidence)**: 0.5 - 0.95 (mặc định: 0.7)
- **Nhãn Tùy Chỉnh**: `accident, vehicle accident, crash`

### Tối Ưu Hóa Stream
- Độ phân giải khung hình: Tự động scale về 640px chiều rộng
- Bỏ qua khung hình: 5 frames (có thể điều chỉnh)
- Kích thước buffer: 4 giây

---

## 🔧 Xử Lý Lỗi Thường Gặp

### Python Server Không Khởi Động
```bash
# Kiểm tra cổng 5000 có trống không
netstat -ano | findstr :5000

# Tắt tiến trình nếu đang chiếm dụng
taskkill /PID <process_id> /F
```

### Lỗi Kết Nối Database ở Java Backend
- Kiểm tra MySQL đang chạy
- Kiểm tra thông tin đăng nhập trong `application.properties`
- Đảm bảo database `traffic_incident_db` đã được tạo

### WebRTC Kết Nối Thất Bại
- Kiểm tra cài đặt firewall
- Đảm bảo Python server đang chạy
- Xóa cache trình duyệt

### Gemini API Vượt Quá Quota
- Kiểm tra tính hợp lệ của API key
- Theo dõi mức sử dụng tại Google AI Studio
- Hệ thống sẽ tự động chuyển sang các model dự phòng

---

## 🤝 Đóng Góp

Chúng tôi hoan nghênh mọi đóng góp! Vui lòng làm theo các bước sau:

1. Fork repository này
2. Tạo feature branch (`git checkout -b feature/TinhNangMoi`)
3. Commit các thay đổi (`git commit -m 'Thêm tính năng mới'`)
4. Push lên branch (`git push origin feature/TinhNangMoi`)
5. Mở Pull Request

---

## 📄 Giấy Phép

Dự án này được phân phối dưới giấy phép MIT License.

---

## 👥 Team

- **Binh Luu** - Project Lead & Full-stack Developer
- 
-
-
---

## 📞 Contact

- GitHub: [@BinhLN1105](https://github.com/BinhLN1105)
- Repository: [Traffic-Accident-Reporter](https://github.com/BinhLN1105/Traffic-Accident-Reporter)

---

<p align="center">
  Made with ❤️ by Team
</p>

<p align="center">
  ⭐ Star us on GitHub — it helps!
</p>
