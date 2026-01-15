"""
AI Report Generator - Java Backend Integration
Calls Java backend API which uses Gemini to generate reports
"""

import os
from typing import Optional

class ReportGenerator:
    """Generate AI reports via Java backend API"""
    
    def __init__(self, api_client=None):
        self.api_client = api_client
        print("✅ Report Generator initialized (Java Backend mode)")
    
    def generate_report(self, before_path: str, during_path: str, after_path: str, incident_type: str, video_path: str = None) -> dict:
        """Send images to Java backend for AI report generation, optional video"""
        
        if not self.api_client:
            return {
                'success': False,
                'report': self._generate_fallback_report(incident_type),
                'incident_id': None
            }
        
        # Call Java API with all 3 images + video
        result = self.api_client.send_full_report(
            before_path, during_path, after_path, incident_type, video_path
        )
        
        if result:
            # Backend Responded 200 OK
            # Check if AI text is present, otherwise use description or status
            ai_text = result.get('aiReport')
            
            if not ai_text:
                # Backend saved it, but maybe AI is slow or empty
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
            # TRUE Connection Failure (result is None)
            return {
                'success': False,
                'report': self._generate_fallback_report(incident_type),
                'incident_id': None
            }
    
    def _generate_fallback_report(self, incident_type: str) -> str:
        """Generate basic report when backend unavailable"""
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
