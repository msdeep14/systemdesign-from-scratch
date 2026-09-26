import time
import requests
import argparse
import concurrent.futures
import uuid

def setup_user_session(base_url, user_index):
    """
    Signs up a dummy user via the web UI and returns an authenticated requests.Session.
    """
    session = requests.Session()
    signup_url = f"{base_url}/users/signup/"
    
    # 1. Get the signup page to get a CSRF token
    try:
        response = session.get(signup_url, timeout=10)
        csrf_token = session.cookies.get('csrftoken')
    except Exception as e:
        return None, f"Failed to load signup page: {e}"

    if not csrf_token:
        return None, "No CSRF token received on signup GET"

    # 2. Perform the signup
    username = f"bench_follower_{uuid.uuid4().hex[:8]}"
    signup_data = {
        'username_display': username,
        'first_name': 'Bench',
        'last_name': 'Marker',
        'password': 'password123',
        'confirm_password': 'password123',
        'csrfmiddlewaretoken': csrf_token
    }
    
    headers = {'Referer': signup_url}
    
    try:
        post_response = session.post(signup_url, data=signup_data, headers=headers, timeout=15)
        # If signup is successful, it usually redirects to newsfeed (HTTP 302) or returns 200
        if post_response.status_code not in (200, 302):
            return None, f"Signup failed with status {post_response.status_code}"
    except Exception as e:
        return None, f"Signup request failed: {e}"

    return session, username

def execute_follow(session, base_url, target_celeb):
    """
    Executes the POST request to follow the target celebrity.
    """
    follow_url = f"{base_url}/users/{target_celeb}/follow/"
    
    # The CSRF token is fetched in the setup phase to avoid flooding Gunicorn with GET requests during the benchmark.
    csrf_token = session.cookies.get('csrftoken')
    if not csrf_token:
        return 0, False, "Missing CSRF token"

    headers = {
        'Referer': f"{base_url}/users/{target_celeb}/",
        'X-CSRFToken': csrf_token  # For AJAX requests, Django often looks for X-CSRFToken
    }
    
    start_time = time.time()
    try:
        # Django's toggle_follow_view requires a POST request
        response = session.post(follow_url, headers=headers, timeout=130)
        elapsed = time.time() - start_time
        if response.status_code == 200:
            return elapsed, True, None
        else:
            return elapsed, False, f"Status code: {response.status_code}"
    except requests.exceptions.Timeout:
        elapsed = time.time() - start_time
        return elapsed, False, "TIMEOUT"
    except Exception as e:
        elapsed = time.time() - start_time
        return elapsed, False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Follow Hot Row Benchmark")
    parser.add_argument("--host", default="http://localhost", help="Base URL (e.g. http://localhost or http://<alb-ip>)")
    parser.add_argument("--concurrency", type=int, default=200, help="Number of concurrent users to simulate")
    parser.add_argument("--target", default="celeb_2m", help="The celebrity username to follow")
    
    args = parser.parse_args()
    base_url = args.host.rstrip('/')
    target_celeb = args.target
    concurrency = args.concurrency

    print(f"Follow Hot Row Benchmark (End-to-End HTTP Simulation)")
    print(f"Targeting: {base_url}/users/{target_celeb}/follow/")
    print("-" * 50)
    
    print(f"Step 1: Setting up {concurrency} authenticated user sessions via /users/signup/...")
    print("This might take a few moments depending on the server speed.")
    
    sessions = []
    
    # We can setup sessions in parallel to speed up the benchmark preparation
    setup_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(setup_user_session, base_url, i) for i in range(concurrency)]
        for future in concurrent.futures.as_completed(futures):
            session, result = future.result()
            if session:
                sessions.append(session)
            else:
                print(f"  Warning: {result}")
                
    print(f"Successfully prepared {len(sessions)} sessions in {time.time() - setup_start:.2f} seconds.")
    if not sessions:
        print("Failed to create any sessions. Exiting.")
        return

    print(f"\nStep 2: Simulating {len(sessions)} concurrent users clicking 'Follow' exactly at the same time...")
    times = []
    errors = 0
    error_msgs = set()

    benchmark_start = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        futures = [executor.submit(execute_follow, sess, base_url, target_celeb) for sess in sessions]
        
        for future in concurrent.futures.as_completed(futures):
            elapsed, success, err = future.result()
            if success:
                times.append(elapsed)
            else:
                errors += 1
                error_msgs.add(err)

    total_time = time.time() - benchmark_start
    
    print("\nBenchmark Results:")
    print("-" * 50)
    print(f"Total Follow Requests Attempted: {len(sessions)}")
    
    if times:
        print(f"Successful Requests: {len(times)}")
        print(f"Failed/Errors: {errors}")
        print(f"Fastest Request: {min(times):.4f} seconds")
        print(f"Slowest Request: {max(times):.4f} seconds")
        print(f"Average Request: {sum(times)/len(times):.4f} seconds")
        print(f"Total Wall Time: {total_time:.4f} seconds")
        print("\nObservation:")
        print("Because the Django view runs `F('follower_count') + 1` directly on the database row,")
        print("PostgreSQL queues all these concurrent requests waiting for the lock on the same row.")
        print("Notice how the slowest request takes substantially longer than the fastest one.")
    else:
        print("All follow requests failed.")
        
    if errors > 0:
        print(f"\nUnique Errors encountered: {error_msgs}")

if __name__ == "__main__":
    main()
