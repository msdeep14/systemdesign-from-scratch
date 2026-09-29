"""
Benchmark: Likes Hot Row Database Lock Contention

N concurrent users all like the SAME celebrity photo simultaneously.
Every request fires: UPDATE photos_photo SET likes_count = likes_count + 1 WHERE id = ?
All requests queue behind a single row lock, even though the DB is otherwise idle.

Usage:
    python benchmark_likes_hot_row.py --host http://<lb-ip> --concurrency 500 --hot-photo-id <id>
"""
import argparse
import concurrent.futures
import time
import uuid

import requests


def setup_user_session(base_url):
    session = requests.Session()
    signup_url = f"{base_url}/users/signup/"
    try:
        session.get(signup_url, timeout=10)
        csrf_token = session.cookies.get("csrftoken")
    except Exception as e:
        return None, None, f"GET failed: {e}"

    signup_data = {
        "username_display": f"bench_{uuid.uuid4().hex[:8]}",
        "first_name": "Bench",
        "last_name": "Marker",
        "password": "password123",
        "confirm_password": "password123",
        "csrfmiddlewaretoken": csrf_token,
    }
    try:
        session.post(
            signup_url,
            data=signup_data,
            headers={"Referer": signup_url},
            timeout=15,
        )
        csrf_token = session.cookies.get("csrftoken")
    except Exception as e:
        return None, None, f"POST failed: {e}"

    return session, csrf_token, None


def execute_like(session, csrf_token, base_url, photo_id):
    like_url = f"{base_url}/photos/{photo_id}/like/"
    headers = {
        "Referer": f"{base_url}/photos/{photo_id}/",
        "X-CSRFToken": csrf_token,
    }
    start = time.time()
    try:
        resp = session.post(like_url, headers=headers, timeout=130)
        return time.time() - start, resp.status_code == 200
    except Exception:
        return time.time() - start, False


def run_test(sessions, base_url, photo_id, name):
    print(f"\n--- {name} ---")
    print(f"  {len(sessions)} concurrent users all liking photo id={photo_id}...")

    start = time.time()
    success = 0
    latencies = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        futures = [
            executor.submit(execute_like, session, csrf, base_url, photo_id)
            for session, csrf in sessions
        ]
        for f in concurrent.futures.as_completed(futures):
            elapsed, ok = f.result()
            latencies.append(elapsed)
            if ok:
                success += 1

    total_time = time.time() - start
    avg = sum(latencies) / len(latencies) if latencies else 0
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0

    print(f"  Success    : {success}/{len(sessions)}")
    print(f"  Total Time : {total_time:.2f}s")
    print(f"  Throughput : {success / total_time:.1f} req/s")
    print(f"  Min        : {latencies[0] * 1000:.0f}ms")
    print(f"  Avg        : {avg * 1000:.0f}ms")
    print(f"  p95        : {p95 * 1000:.0f}ms")
    print(f"  p99        : {p99 * 1000:.0f}ms")
    print(f"  Max        : {latencies[-1] * 1000:.0f}ms")
    return total_time



def main():
    parser = argparse.ArgumentParser(description="Benchmark: Likes Hot Row")
    parser.add_argument("--host", default="http://localhost", help="Target host URL")
    parser.add_argument("--concurrency", type=int, default=300, help="Number of concurrent users")
    parser.add_argument("--hot-photo-id", type=int, required=True, help="Celebrity photo ID")
    args = parser.parse_args()

    base_url = args.host.rstrip("/")

    print("Benchmark: Likes Hot Row Database Lock Contention")
    print("=" * 60)
    print(f"Host        : {base_url}")
    print(f"Concurrency : {args.concurrency} users")
    print(f"Hot Photo   : id={args.hot_photo_id}")
    print(f"\nPreparing {args.concurrency} user sessions...")

    sessions = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(setup_user_session, base_url) for _ in range(args.concurrency)]
        for f in concurrent.futures.as_completed(futures):
            session, csrf, err = f.result()
            if session:
                sessions.append((session, csrf))

    print(f"{len(sessions)} sessions ready.")

    total_time = run_test(sessions, base_url, args.hot_photo_id, "HOT ROW: All users like the same photo")

    print("\n" + "=" * 60)
    print("CONCLUSION")
    print("=" * 60)
    print(f"  {len(sessions)} concurrent users all fired: UPDATE photos_photo SET likes_count = likes_count + 1 WHERE id = {args.hot_photo_id}")
    print(f"  All {len(sessions)} requests serialized behind a single row lock.")
    print(f"  Total wall time: {total_time:.2f}s for {len(sessions)} requests.")
    print(f"  Expected without lock contention: <1s")


if __name__ == "__main__":
    main()
