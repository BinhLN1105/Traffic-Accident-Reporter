import requests
import os

class APIClient:
    """
    Client để giao tiếp với Java Backend API
    Xử lý việc gửi báo cáo sự cố và lấy lịch sử phát hiện
    """
    def __init__(self, base_url="http://localhost:8080/api"):
        """Khởi tạo client với URL cơ sở của backend"""
        self.base_url = base_url

    def send_incident(self, image_path, incident_type, location="Camera-01"):
        """
        Gửi báo cáo sự cố đơn giản (1 ảnh) đến backend
        """
        endpoint = f"{self.base_url}/incidents"
        
        try:
            # Mở file ảnh và gửi kèm metadata
            with open(image_path, 'rb') as img:
                files = {'image': img}
                data = {
                    'type': incident_type,
                    'location': location
                }
                response = requests.post(endpoint, files=files, data=data)
                
                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"Error: {response.status_code} - {response.text}")
                    return None
        except Exception as e:
            print(f"API Error: {e}")
            return None
    
    def send_full_report(self, before_path, during_path, after_path, incident_type, video_path=None):
        """
        Gửi báo cáo đầy đủ với 3 ảnh chụp (trước, trong, sau) đến backend để tạo báo cáo AI
        Có thể kèm video nếu có
        """
        url = f"{self.base_url}/incidents/report"
        
        try:
            # Chuẩn bị dữ liệu multipart form
            files = {}
            
            if before_path and os.path.exists(before_path):
                files['imageBefore'] = open(before_path, 'rb')
            if during_path and os.path.exists(during_path):
                files['imageDuring'] = open(during_path, 'rb')
            if after_path and os.path.exists(after_path):
                files['imageAfter'] = open(after_path, 'rb')
            
            # Thêm video nếu có và file tồn tại
            if video_path and os.path.exists(video_path):
                files['video'] = open(video_path, 'rb')
            
            data = {
                'type': incident_type,
                'description': f'Auto-detected {incident_type}' if incident_type != 'No Accident' else 'Video analyzed: No accident detected.'
            }
            
            # Tăng timeout cho việc upload video (có thể lớn)
            response = requests.post(url, files=files, data=data, timeout=60)
            
            # Đóng tất cả file đã mở
            for f in files.values():
                if hasattr(f, 'close'):
                    f.close()
                elif isinstance(f, tuple) and len(f) > 1 and hasattr(f[1], 'close'):
                    f[1].close()
            
            if response.status_code == 200 or response.status_code == 201:
                result = response.json()
                print(f"✅ Full report sent successfully, ID: {result.get('id')}")
                return result
            else:
                print(f"❌ Failed to send report: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"API Error: {e}")
            return None
    
    def get_history(self, limit=50):
        """
        Lấy lịch sử phát hiện từ backend
        Giới hạn số lượng kết quả trả về
        """
        url = f"{self.base_url}/incidents"
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                incidents = response.json()
                print(f"✅ Fetched {len(incidents)} incidents from history")
                # Giới hạn số lượng kết quả trả về
                return incidents[:limit]
            else:
                print(f"❌ Failed to fetch history: {response.status_code}")
                return []
        except Exception as e:
            print(f"API Error fetching history: {e}")
            return []
