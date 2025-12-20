# 🚦 Traffic Accident AI Reporter

> **Hệ Thống Giám Sát Tai Nạn Giao Thông Thế Hệ Mới, được hỗ trợ bởi YOLOv8 và Google Gemini 2.0 AI.**

![Project Status](https://img.shields.io/badge/Status-Active-success?style=flat-square)
![Java](https://img.shields.io/badge/Backend-Spring%20Boot-green?style=flat-square&logo=springboot)
![Python](https://img.shields.io/badge/AI%20Core-Python%20%7C%20YOLOv8-blue?style=flat-square&logo=python)
![AI](https://img.shields.io/badge/Intelligence-Google%20Gemini%202.0-orange?style=flat-square&logo=google)
![License](https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square)

## 📖 Tổng Quan

**Traffic Accident Reporter** là một hệ thống tự động được thiết kế để phát hiện, phân tích và báo cáo các sự cố giao thông theo thời gian thực. Bằng cách kết hợp tốc độ của thị giác máy tính (**YOLOv8**) với khả năng phân tích nhận thức của **Generative AI (Gemini 2.0)**, hệ thống không chỉ xác định được tai nạn mà còn "hiểu" được chúng—cung cấp các báo cáo chi tiết về mức độ nghiêm trọng, nguyên nhân và đề xuất hướng xử lý.

Hệ thống sở hữu **Cơ Chế Dự Phòng Mạnh Mẽ (Robust Fallback Mechanism)**, đảm bảo khả năng hoạt động 99.9% ngay cả khi dịch vụ AI bị quá tải, nhờ chuỗi mô hình thông minh (`Gemini 2.0 Flash` → `Gemini 1.5 Flash 8b` → `Gemini 2.5`).

---

## ✨ Tính Năng Chính

- **📹 Phát Hiện Thời Gian Thực**: Tự động phát hiện tai nạn sử dụng mô hình thị giác máy tính YOLOv8.
- **🧠 Phân Tích Bằng AI**:
  - Tạo báo cáo sự cố toàn diện bằng **Google Gemini**.
  - Phân tích "Thời Điểm Va Chạm" (Impact Moment) để xác định lỗi và mức độ nghiêm trọng.
  - Đề xuất hành động tức thời (ví dụ: "Gọi Cứu Thương", "Báo Cảnh Sát").
- **🛡️ Tự Động Thử Lại & Dự Phòng**:
  - Hệ thống thông minh xử lý lỗi Quá Tải API (503) và Giới Hạn Quota (429).
  - Tự động chuyển đổi giữa các mô hình hiệu năng cao và mô hình khả dụng cao.
- **📉 Tối Ưu Hóa Hiệu Suất**:
  - Sử dụng công nghệ "Single Key Frame" để giảm thiểu dung lượng dữ liệu trong khi vẫn tối đa hóa độ chính xác phân tích.
- **🖥️ Dashboard Trực Tiếp**: Giao diện web thân thiện để xem video đã xử lý và báo cáo AI.

---

## 🏗️ Kiến Trúc Hệ Thống

Dự án bao gồm ba thành phần chính hoạt động hài hòa:

1.  **Backend (Java Spring Boot)**: Bộ điều phối trung tâm. Quản lý các API endpoint, lưu trữ cơ sở dữ liệu (MySQL) và điều phối giữa người dùng và dịch vụ AI.
2.  **AI Client (Python)**: Lớp "Thị Giác". Chạy YOLOv8 để phát hiện đối tượng và xử lý video (cắt ảnh, định dạng).
3.  **Frontend (Vanilla JS/HTML)**: Bảng điều khiển (Dashboard) nhẹ nhàng, phản hồi nhanh cho người dùng cuối.

---

## 🚀 Hướng Dẫn Cài Đặt

### Yêu Cầu Tiên Quyết

- **Java JDK 21+**
- **Python 3.10+**
- **Maven**
- **Google Gemini API Key**

### 1. 🧠 Cài Đặt AI Client (Python)

Di chuyển vào thư mục `traffic-ai-client`:

```bash
cd traffic-ai-client
pip install -r requirements.txt
python server.py
```

*Server Python sẽ khởi chạy tại cổng `5000`.*

### 2. 🛡️ Cài Đặt Backend (Spring Boot)

Di chuyển vào thư mục `incident-reporter`.  
Chạy bằng Maven:

```bash
cd incident-reporter
mvn spring-boot:run
```

*Backend sẽ khởi chạy tại cổng `8080`.*

### 3. 🌐 Truy Cập Dashboard

Đơn giản chỉ cần mở file `traffic-frontend/index.html` trong trình duyệt của bạn (hoặc chạy qua Live Server).

---

## 💡 Cơ Chế Hoạt Động

1.  **Upload**: Người dùng tải video camera giao thông lên qua Dashboard.
2.  **Phát Hiện**: Dịch vụ Python quét video bằng YOLOv8.
3.  **Kích Hoạt**: Nếu phát hiện tai nạn (nhãn như "crash", "accident"), hệ thống sẽ chụp lại **Khung Hình Va Chạm (Impact Frame)** chính xác nhất.
4.  **Phân Tích**: Backend Java gửi khung hình này tới **Gemini AI**.
5.  **Báo Cáo**: Gemini trả về báo cáo chi tiết (Mô tả, Mức độ, Giải pháp), dữ liệu được lưu vào database và hiển thị lên Dashboard.

---

## 🛠️ Công Nghệ Sử Dụng

-   **Backend**: Java 21, Spring Boot 3.2, Hibernate/JPA.
-   **AI/ML**: Python 3, Ultralytics YOLOv8, OpenCV, Google Generative AI SDK.
-   **Frontend**: HTML5, CSS3, JavaScript (ES6+), Bootstrap/Tailwind (tùy chọn).
-   **Database**: MySQL.

---

## 🤝 Đóng Góp

Mọi đóng góp đều được hoan nghênh! Vui lòng fork repository và gửi pull request.

---

<p align="center">
  Made with ❤️ by Team
</p>
