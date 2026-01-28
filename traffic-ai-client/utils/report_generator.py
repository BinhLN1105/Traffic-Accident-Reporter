"""
Bộ tạo Báo cáo AI - Tích hợp với Java Backend
Gọi API của Java backend, backend này sử dụng Gemini để tạo báo cáo
"""

import os
from typing import Optional

class ReportGenerator:
    """
    Tạo báo cáo AI thông qua Java Backend API
    Backend sẽ xử lý việc phân tích ảnh và tạo báo cáo bằng Gemini AI
    """
    
    def __init__(self, api_client=None):
        """Khởi tạo generator với API client để giao tiếp với backend"""
        self.api_client = api_client
        print("✅ Report Generator initialized (Java Backend mode)")
    
    def generate_report(self, before_path: str, during_path: str, after_path: str, incident_type: str, video_path: str = None) -> dict:
        """
        Gửi 3 ảnh đến Java backend để tạo báo cáo AI
        Có thể kèm video nếu có
        
        Logic:
        - Nếu không có API client, trả về báo cáo fallback
        - Gửi 3 ảnh + video đến backend
        - Nếu backend phản hồi thành công, kiểm tra xem có báo cáo AI không
        - Nếu không có báo cáo AI (có thể đang xử lý), tạo báo cáo tạm thời
        """
        
        if not self.api_client:
            return {
                'success': False,
                'report': self._generate_fallback_report(incident_type),
                'incident_id': None
            }
        
        # Gọi Java API với 3 ảnh + video (nếu có)
        result = self.api_client.send_full_report(
            before_path, during_path, after_path, incident_type, video_path
        )
        
        if result:
            # Backend phản hồi 200 OK
            # Kiểm tra xem có báo cáo AI không, nếu không thì dùng mô tả hoặc trạng thái
            ai_text = result.get('aiReport')
            
            if not ai_text:
                # Backend đã lưu nhưng có thể AI đang xử lý hoặc trống
                # Tạo báo cáo tạm thời với thông tin có sẵn
                desc = result.get('description') or result.get('description_text')
                ai_text = (
                    f"## ✅ Incident Reported Successfully\n\n"
                    f"**Incident ID:** {result.get('id')}\n"
                    f"**Status:** Saved to Database.\n"
                    f"**Note:** AI Analysis might be processing in the background or disabled on server.\n\n"
                    f"**Description:** {desc if desc else 'No description provided.'}"
                )
            
            return {
                'success': True,
                'report': ai_text,
                'incident_id': result.get('id')
            }
        else:
            # Lỗi kết nối thực sự (result là None)
            return {
                'success': False,
                'report': self._generate_fallback_report(incident_type),
                'incident_id': None
            }
    
    def _generate_fallback_report(self, incident_type: str) -> str:
        """
        Tạo báo cáo cơ bản khi backend không khả dụng
        Được dùng khi không thể kết nối đến backend hoặc backend lỗi
        """
        import time
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        return f"""
## 🚨 Báo cáo Tai nạn Giao thông

**Loại sự cố:** {incident_type}
**Thời gian:** {timestamp}
**Trạng thái:** Đã phát hiện và lưu ảnh

### Thông tin
- ✅ 3 ảnh đã được chụp (Before/During/After)
- ⚠️ AI Report không khả dụng (backend offline)

### Lưu ý
Report này sẽ được tạo bởi Java backend khi upload thành công.

---
*Fallback report - Java backend không phản hồi*
"""
