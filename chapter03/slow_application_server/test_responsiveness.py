import time
import requests
import sys
import os
import uuid

def test_responsiveness(host, port=80):
    base_url = f"http://{host}:{port}" if port != 80 else f"http://{host}"
    print(f"Authenticating with {host}:{port}...")
    
    session = requests.Session()
    signup_url = f"{base_url}/users/signup/"
    
    try:
        response = session.get(signup_url, timeout=5)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to connect to the server: {e}")
        return
        
    csrftoken = session.cookies.get('csrftoken')
    if not csrftoken:
        print("Failed to get CSRF token. Cannot authenticate.")
        return
        
    dummy_username = f"fasttest_{uuid.uuid4().hex[:6]}"
    signup_data = {
        'csrfmiddlewaretoken': csrftoken,
        'username_display': dummy_username,
        'first_name': 'Fast',
        'last_name': 'Tester',
        'password': 'password123',
        'password_confirm': 'password123'
    }
    
    print(f"Creating dummy user '{dummy_username}'...")
    try:
        # Register the user, which logs them in and redirects to newsfeed
        session.post(signup_url, data=signup_data, headers={'Referer': signup_url}, timeout=5)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Authentication request failed: {e}")
        return
        
    print(f"Uploading 3 dummy photos to populate the newsfeed...")
    upload_url = f"{base_url}/photos/upload/"
    
    # Read actual image from disk to pass Pillow validation and upload to S3
    image_path = os.path.join(os.path.dirname(__file__), 'sdoa-book-fair.jpg')
    try:
        with open(image_path, 'rb') as f:
            real_image = f.read()
    except Exception as e:
        print(f"Failed to load real image: {e}")
        return

    for i in range(3):
        upload_data = {
            'csrfmiddlewaretoken': session.cookies.get('csrftoken'),
            'caption': f'Real Photo {i+1} for testing S3'
        }
        files = {
            'image': (f'test_photo_{i}.jpg', real_image, 'image/jpeg')
        }
        try:
            resp = session.post(upload_url, data=upload_data, files=files, headers={'Referer': upload_url})
            if resp.status_code == 200:
                print(f"  - Uploaded photo {i+1}")
        except Exception as e:
            print(f"  - Failed to upload photo {i+1}: {e}")

    newsfeed_url = f"{base_url}/"
    print(f"Testing responsiveness of {newsfeed_url} as authenticated user...")
    
    start_time = time.time()
    try:
        # Using a timeout of 5 seconds to not hang forever
        response = session.get(newsfeed_url, timeout=5)
        elapsed = time.time() - start_time
        print(f"Response Status Code: {response.status_code}")
        print(f"Time Taken: {elapsed:.3f} seconds")
        
        print("\n--- Detailed Request/Response Log for Appendix ---")
        print("REQUEST HEADERS:")
        for k, v in response.request.headers.items():
            print(f"{k}: {v}")
        print("\nRESPONSE HEADERS:")
        for k, v in response.headers.items():
            print(f"{k}: {v}")
        print("--------------------------------------------------\n")
        
        if elapsed > 2:
            print("WARNING: Request took longer than 2 seconds!")
        else:
            print("SUCCESS: Request was fast.")
    except requests.exceptions.Timeout:
        elapsed = time.time() - start_time
        print(f"ERROR: Request timed out after {elapsed:.3f} seconds! The server is blocked.")
    except Exception as e:
        print(f"ERROR: Request failed: {e}")

# How to run: 
# python chapter03/slow_application_server/test_responsiveness.py 192.168.x.x
if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    test_responsiveness(host, port)
