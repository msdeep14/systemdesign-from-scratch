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
    
    # A valid tiny 1x1 JPEG byte string to pass Pillow validation
    tiny_jpeg = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\xff\xdb\x00C\x01\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xc4\x00\x1f\x01\x00\x03\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x11\x00\x02\x01\x02\x04\x04\x03\x04\x07\x05\x04\x04\x00\x01\x02w\x00\x01\x02\x03\x11\x04\x05!1\x06\x12AQ\x07aq\x13"2\x81\x08\x14B\x91\xa1\xb1\xc1\t#3R\xf0\x15br\xd1\n\x16$4\xe1%\xf1\x17\x18\x19\x1a&\'()*56789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xfd\xfc\xa8\xff\x00\xff\xd9'

    for i in range(3):
        upload_data = {
            'csrfmiddlewaretoken': session.cookies.get('csrftoken'),
            'caption': f'Dummy Photo {i+1} for testing'
        }
        files = {
            'image': (f'dummy_{i}.jpg', tiny_jpeg, 'image/jpeg')
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
        print("RESPONSE BODY (first 250 chars):")
        print(response.text[:250] + "\n[...]")
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
