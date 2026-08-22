import time
import requests
import concurrent.futures
import sys

import random
import uuid


def make_request(base_url):
    try:
        session = requests.Session()
        # 1. Get the signup page to get a CSRF token
        signup_url = f"{base_url}/users/signup/"
        response = session.get(signup_url, timeout=10)
        csrftoken = session.cookies.get("csrftoken")

        if not csrftoken:
            return "NO_CSRF"

        # 2. Perform a CPU-heavy POST request (password hashing)
        dummy_username = f"load_{uuid.uuid4().hex[:8]}"
        signup_data = {
            "csrfmiddlewaretoken": csrftoken,
            "username_display": dummy_username,
            "first_name": "Load",
            "last_name": "Tester",
            "password": "heavy_password_123!",
            "password_confirm": "heavy_password_123!",
        }

        resp = session.post(
            signup_url, data=signup_data, headers={"Referer": signup_url}, timeout=15
        )
        return resp.status_code
    except requests.exceptions.RequestException:
        return "FAILED"


def simulate_load(host, port=80, concurrent_users=50):
    base_url = f"http://{host}:{port}"
    print(
        f"Starting heavy CPU load simulation (concurrent signups) against {base_url} with {concurrent_users} workers..."
    )

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=concurrent_users
    ) as executor:
        while True:
            # Submit a batch of CPU-intensive signup requests
            futures = [
                executor.submit(make_request, base_url) for _ in range(concurrent_users)
            ]
            results = []
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

            # Count the status codes
            status_counts = {}
            for res in results:
                status_counts[res] = status_counts.get(res, 0) + 1

            print(f"Batch completed. Status codes: {status_counts}")
            # Add a slight delay to avoid instantly overloading the OS's socket limits,
            # we want the docker container to be the bottleneck.
            time.sleep(0.1)


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    simulate_load(host, port, workers)
