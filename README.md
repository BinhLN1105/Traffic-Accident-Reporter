# 🚦 Traffic Accident AI Reporter

> **A Next-Gen Traffic Incident Monitoring System powered by YOLOv8 and Google Gemini 2.0 AI.**

![Project Status](https://img.shields.io/badge/Status-Active-success?style=flat-square)
![Java](https://img.shields.io/badge/Backend-Spring%20Boot-green?style=flat-square&logo=springboot)
![Python](https://img.shields.io/badge/AI%20Core-Python%20%7C%20YOLOv8-blue?style=flat-square&logo=python)
![AI](https://img.shields.io/badge/Intelligence-Google%20Gemini%202.0-orange?style=flat-square&logo=google)
![License](https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square)

## 📖 Overview

**Traffic Accident Reporter** is an automated system designed to detect, analyze, and report traffic incidents in real-time. By combining the speed of computer vision (**YOLOv8**) with the cognitive analysis capabilities of **Generative AI (Gemini 2.0)**, the system not only identifies accidents but also understands them—providing detailed reports on severity, causes, and recommended handling.

The system features a **Robust Fallback Mechanism** ensuring 99.9% availability even when AI services are overloaded, utilizing a smart chain of models (`Gemini 2.0 Flash` → `Gemini 1.5 Flash 8b` → `Gemini 2.5`).

---

## ✨ Key Features

- **📹 Real-time Detection**: Automatically detects accidents using YOLOv8 computer vision models.
- **🧠 AI-Powered Analysis**:
  - Generates comprehensive incident reports using **Google Gemini**.
  - Analyzes the "Impact Moment" (Key Frame) to determine fault and severity.
  - Suggests immediate actions (e.g., "Call Ambulance", "Notify Police").
- **🛡️ Smart Retry & Fallback**:
  - Intelligent system handles API Overloads (503) and Quota Limits (429).
  - Auto-switches between high-performance and high-availability models.
- **📉 Optimized Performance**:
  - Uses "Single Key Frame" technology to minimize data usage while maximizing analysis accuracy.
- **🖥️ Live Dashboard**: A user-friendly web interface to view live processed videos and AI reports.

---

## 🏗️ System Architecture

The project consists of three main components working in harmony:

1.  **Backend (Java Spring Boot)**: The central orchestrator. Manages API endpoints, database storage (MySQL), and coordinates between the user and the AI service.
2.  **AI Client (Python)**: The "Vision" layer. Runs YOLOv8 for object detection and handles video processing (snapshotting, formatting).
3.  **Frontend (Vanilla JS/HTML)**: A lightweight, responsive dashboard for end-users.

---

## 🚀 Getting Started

### Prerequisites

- **Java JDK 21+**
- **Python 3.10+**
- **Maven**
- **Google Gemini API Key**

### 1. 🧠 Setup AI Client (Python)

Navigate to `traffic-ai-client`:

```bash
cd traffic-ai-client
pip install -r requirements.txt
python server.py
```

*The Python server will start on port `5000`.*

### 2. 🛡️ Setup Backend (Spring Boot)

Navigate to `incident-reporter`.  
Running with Maven:

```bash
cd incident-reporter
mvn spring-boot:run
```

*The Backend will start on port `8080`.*

### 3. 🌐 Access the Dashboard

Simply open `traffic-frontend/index.html` in your browser (or serve it via Live Server).

---

## 💡 How It Works

1.  **Upload**: User uploads a traffic camera video via the Dashboard.
2.  **Detection**: The Python service scans the video using YOLOv8.
3.  **Trigger**: If an accident is detected (labels like "crash", "accident"), the system captures the precise **Impact Frame**.
4.  **Analysis**: The Java Backend sends this frame to **Gemini AI**.
5.  **Report**: Gemini returns a detailed report (Description, Severity, Solutions), which is saved to the database and displayed on the Dashboard.

---

## 🛠️ Technology Stack

-   **Backend**: Java 21, Spring Boot 3.2, Hibernate/JPA.
-   **AI/ML**: Python 3, Ultralytics YOLOv8, OpenCV, Google Generative AI SDK.
-   **Frontend**: HTML5, CSS3, JavaScript (ES6+), Bootstrap/Tailwind (optional).
-   **Database**: MySQL.

---

## 🤝 Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

---

<p align="center">
  Made with ❤️ by Team
</p>