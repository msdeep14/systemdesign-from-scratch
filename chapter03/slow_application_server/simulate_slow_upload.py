import socket
import time
import sys
import os

import requests
import uuid

def slow_upload(host, port=80, path='/photos/upload/'):
    print(f"Authenticating with {host}:{port}...")
    base_url = f"http://{host}:{port}" if port != 80 else f"http://{host}"
    
    # 1. Start a session and get CSRF token
    session = requests.Session()
    signup_url = f"{base_url}/users/signup/"
    
    try:
        response = session.get(signup_url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to connect to the server: {e}")
        return
        
    csrftoken = session.cookies.get('csrftoken')
    if not csrftoken:
        print("Failed to get CSRF token from signup page. Cannot authenticate.")
        return
        
    # 2. Register a dummy user to get a valid authenticated session
    dummy_username = f"slowtest_{uuid.uuid4().hex[:6]}"
    signup_data = {
        'csrfmiddlewaretoken': csrftoken,
        'username_display': dummy_username,
        'first_name': 'Slow',
        'last_name': 'Tester',
        'password': 'password123',
        'password_confirm': 'password123'
    }
    
    print(f"Creating dummy user '{dummy_username}'...")
    response = session.post(signup_url, data=signup_data, headers={'Referer': signup_url})
    
    # Django redirects to newsfeed on successful login/signup
    if 'sessionid' not in session.cookies:
        print("Failed to get a session cookie. Authentication might have failed.")
        return
        
    sessionid = session.cookies.get('sessionid')
    new_csrftoken = session.cookies.get('csrftoken', csrftoken)
    
    print("Authentication successful! Initiating raw slow socket upload...")
    
    # 3. Perform the slow raw socket upload using the valid cookies
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body_start = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo"; filename="fake_photo.jpg"\r\n'
            f'Content-Type: image/jpeg\r\n\r\n'
        )
        body_end = f"\r\n--{boundary}--\r\n"
        
        # 1.9MB of dummy data (staying under the 2MB architecture limit)
        dummy_data_size = int(1.9 * 1024 * 1024)
        content_length = len(body_start) + dummy_data_size + len(body_end)
        
        headers = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Cookie: csrftoken={new_csrftoken}; sessionid={sessionid}\r\n"
            f"X-CSRFToken: {new_csrftoken}\r\n"
            f"Content-Type: multipart/form-data; boundary={boundary}\r\n"
            f"Content-Length: {content_length}\r\n"
            f"Connection: keep-alive\r\n\r\n"
        )
        
        print("Sending headers (including session and CSRF cookies)...")
        s.sendall(headers.encode('utf-8'))
        s.sendall(body_start.encode('utf-8'))
        
        print("Starting slow data upload (simulating bad 3G connection)...")
        chunk_size = 8192
        bytes_sent = 0
        
        while bytes_sent < dummy_data_size:
            chunk = b'0' * min(chunk_size, dummy_data_size - bytes_sent)
            s.sendall(chunk)
            bytes_sent += len(chunk)
            print(f"Uploaded {bytes_sent}/{dummy_data_size} bytes...")
            time.sleep(1) # Sleep 1 second between chunks to tie up the server!
            
        s.sendall(body_end.encode('utf-8'))
        print("Upload complete. Waiting for response...")
        
        response = s.recv(4096)
        print("Response received:")
        print(response.decode('utf-8'))
        s.close()
        
    except Exception as e:
        print(f"Error during socket upload: {e}")

# How to run: 
# python chapter03/slow_application_server/simulate_slow_upload.py 192.168.x.x
if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    slow_upload(host, port)
