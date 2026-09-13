import os
import time
import requests
import argparse
from io import BytesIO
from PIL import Image

def create_dummy_image():
    # Create a 100x100 solid color image in memory
    img = Image.new('RGB', (100, 100), color = 'red')
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_byte_arr.seek(0)
    return img_byte_arr.read()

def benchmark_upload(username, base_url, password="password123"):
    session = requests.Session()
    login_url = f"{base_url}/users/login/"
    upload_url = f"{base_url}/photos/upload/"
    
    print(f"Logging in as {username}...")
    try:
        # Get CSRF token
        response = session.get(login_url)
        csrf_token = response.cookies.get('csrftoken')
        
        # Login
        login_data = {
            'username': username,
            'password': password,
            'csrfmiddlewaretoken': csrf_token
        }
        
        # Need to include referer for CSRF to pass sometimes
        headers = {'Referer': login_url}
        login_response = session.post(login_url, data=login_data, headers=headers)
        
        if login_response.status_code != 200:
            print(f"  Login failed for {username}. Status: {login_response.status_code}")
            return
        
        # Refresh CSRF token for next POST
        csrf_token = session.cookies.get('csrftoken')
        headers = {'Referer': upload_url}
        
        # Prepare upload
        image_bytes = create_dummy_image()
        files = {
            'image': ('test_image.jpg', image_bytes, 'image/jpeg')
        }
        data = {
            'caption': f"Benchmark upload by {username}",
            'csrfmiddlewaretoken': csrf_token
        }
        
        print(f"  Uploading photo...")
        start_time = time.time()
        
        # We might get a timeout exception if Gunicorn times out (e.g. 120s limit)
        upload_response = session.post(upload_url, data=data, files=files, headers=headers, timeout=130)
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        if upload_response.status_code == 200:
            print(f"  Upload Time: {elapsed:.2f}s")
        else:
            print(f"  Upload failed with status code {upload_response.status_code} after {elapsed:.2f}s")
            
    except requests.exceptions.Timeout:
        print(f"  Upload TIMEOUT (took >130s)")
    except Exception as e:
        print(f"  Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload Benchmark")
    parser.add_argument("--host", default="http://localhost", help="Base URL of the Photoz app (e.g. http://<aws-load-balancer-ip>)")
    args = parser.parse_args()
    
    # Strip trailing slash if present
    base_url = args.host.rstrip('/')

    print("Upload Benchmark")
    print(f"Targeting: {base_url}")
    print("-" * 50)
    users_to_test = ["celeb_500k", "celeb_1m", "celeb_2m"]
    
    for user in users_to_test:
        benchmark_upload(user, base_url)
        print("-" * 50)
