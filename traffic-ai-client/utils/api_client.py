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
            print(f"Connection Error: {e}")
            return None
