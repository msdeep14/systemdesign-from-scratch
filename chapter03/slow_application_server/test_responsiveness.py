import time
import requests
import sys
import os

def test_responsiveness(url):
    print(f"Testing responsiveness of {url}")
    start_time = time.time()
    try:
        # Using a timeout of 5 seconds to not hang forever
        response = requests.get(url, timeout=5)
        elapsed = time.time() - start_time
        print(f"Response Status Code: {response.status_code}")
        print(f"Time Taken: {elapsed:.3f} seconds")
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
    url = f"http://{host}/newsfeed/" 
    # Just hitting the main newsfeed page which does not require authentication to get a 200 or 302
    test_responsiveness(url)
