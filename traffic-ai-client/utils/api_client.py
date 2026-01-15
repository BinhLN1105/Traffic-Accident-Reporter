import requests
import os

class APIClient:
    def __init__(self, base_url="http://localhost:8080/api"):
        self.base_url = base_url

    def send_incident(self, image_path, incident_type, location="Camera-01"):
        """
        Sends an incident report to the backend.
        """
        endpoint = f"{self.base_url}/incidents"
        
        try:
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
        """Send all 3 snapshots to backend for AI report generation, optional video"""
        url = f"{self.base_url}/incidents/report"
        
        try:
            # Prepare multipart form data with 3 images
            # NOTE: We can't use with open() for multiple files easily in one block without ExitStack
            # So we open them and ensure they close
            files = {
                'imageBefore': open(before_path, 'rb'),
                'imageDuring': open(during_path, 'rb'),
                'imageAfter': open(after_path, 'rb')
            }
            
            if video_path and os.path.exists(video_path):
                files['video'] = open(video_path, 'rb')
            
            data = {
                'type': incident_type,
                'description': f'Auto-detected {incident_type}'
            }
            
            response = requests.post(url, files=files, data=data, timeout=60) # Increased timeout for video upload
            
            # Close files
            for f in files.values():
                f.close()
            
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
        """Get detection history from backend"""
        url = f"{self.base_url}/incidents"  # Fixed: removed duplicate /api
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                incidents = response.json()
                print(f"✅ Fetched {len(incidents)} incidents from history")
                return incidents[:limit]  # Limit results
            else:
                print(f"❌ Failed to fetch history: {response.status_code}")
                return []
        except Exception as e:
            print(f"API Error fetching history: {e}")
            return []
