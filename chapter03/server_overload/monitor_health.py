import time
import requests
import sys


def monitor(host, port=80):
    url = f"http://{host}:{port}/"
    print(f"Monitoring {url}...")
    while True:
        try:
            start_time = time.time()
            response = requests.get(url, timeout=5)
            elapsed = time.time() - start_time
            if response.status_code == 200:
                print(f"[{time.strftime('%X')}] OK - {elapsed:.2f}s")
            else:
                print(
                    f"[{time.strftime('%X')}] ERROR {response.status_code} - {elapsed:.2f}s"
                )
        except requests.exceptions.RequestException as e:
            print(f"[{time.strftime('%X')}] FAILED - {e}")
        time.sleep(1)


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    monitor(host, port)
