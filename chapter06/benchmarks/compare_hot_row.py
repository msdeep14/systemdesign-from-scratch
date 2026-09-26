import time
import requests
import argparse
import concurrent.futures
import uuid

def setup_user_session(base_url):
    session = requests.Session()
    signup_url = f"{base_url}/users/signup/"
    
    try:
        response = session.get(signup_url, timeout=10)
        csrf_token = session.cookies.get('csrftoken')
    except Exception as e:
        return None, None, f"Failed GET: {e}"

    username = f"bench_{uuid.uuid4().hex[:8]}"
    signup_data = {
        'username_display': username,
        'first_name': 'Bench',
        'last_name': 'Marker',
        'password': 'password123',
        'confirm_password': 'password123',
        'csrfmiddlewaretoken': csrf_token
    }
    
    try:
        session.post(signup_url, data=signup_data, headers={'Referer': signup_url}, timeout=15)
        csrf_token = session.cookies.get('csrftoken')
    except Exception as e:
        return None, None, f"Failed POST: {e}"

    return session, username, csrf_token

def execute_follow(session, csrf_token, base_url, target_celeb):
    follow_url = f"{base_url}/users/{target_celeb}/follow/"
    headers = {
        'Referer': f"{base_url}/users/{target_celeb}/",
        'X-CSRFToken': csrf_token
    }
    
    start_time = time.time()
    try:
        response = session.post(follow_url, headers=headers, timeout=130)
        return time.time() - start_time, response.status_code == 200
    except Exception:
        return time.time() - start_time, False

def run_test(sessions_data, base_url, targets, name):
    print(f"\n--- Running Test: {name} ---")
    print(f"Simulating {len(sessions_data)} users following...")
    
    start = time.time()
    success_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sessions_data)) as executor:
        futures = []
        for i, (session, _, csrf_token) in enumerate(sessions_data):
            target = targets[i % len(targets)]
            futures.append(executor.submit(execute_follow, session, csrf_token, base_url, target))
            
        for future in concurrent.futures.as_completed(futures):
            elapsed, success = future.result()
            if success:
                success_count += 1
                
    total_time = time.time() - start
    print(f"Success: {success_count}/{len(sessions_data)}")
    print(f"Total Time: {total_time:.2f} seconds")
    print(f"Throughput: {success_count / total_time:.2f} requests/second")
    return total_time

def main():
    parser = argparse.ArgumentParser(description="Compare Scattered vs Concentrated Database Load")
    parser.add_argument('--host', type=str, default='http://localhost', help='Target host URL')
    parser.add_argument('--concurrency', type=int, default=300, help='Number of concurrent users')
    args = parser.parse_args()

    base_url = args.host.rstrip('/')
    concurrency = args.concurrency
    
    print("Proof of Hot Row Database Lock via Throughput Comparison")
    print(f"Preparing {concurrency} follower sessions and {concurrency} dummy celebrities...")
    
    sessions_data = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(setup_user_session, base_url) for _ in range(concurrency * 2)]
        for future in concurrent.futures.as_completed(futures):
            session, username, csrf = future.result()
            if session:
                sessions_data.append((session, username, csrf))
                
    if len(sessions_data) < concurrency * 2:
        print("Failed to setup enough sessions.")
        return

    followers = sessions_data[:concurrency]
    celebrities = [data[1] for data in sessions_data[concurrency:]]
    
    print("\nPhase 1: SCATTERED (No Hot Row)")
    print(f"{concurrency} users follow {concurrency} DIFFERENT celebrities (No DB lock contention)")
    time_scattered = run_test(followers, base_url, celebrities, "Scattered Load")
    
    print("\nPhase 2: CONCENTRATED (The Hot Row)")
    print(f"{concurrency} users follow ONE SINGLE celebrity (Massive DB lock contention)")
    time_concentrated = run_test(followers, base_url, ["celeb_2m"], "Concentrated Load")
    
    print("\n--- Conclusion ---")
    print(f"Scattered Time: {time_scattered:.2f}s")
    print(f"Concentrated Time: {time_concentrated:.2f}s")
    
    if time_concentrated > time_scattered:
        print(f"The Hot Row made the system {time_concentrated / time_scattered:.1f}x SLOWER under the exact same concurrency!")
        print("This proves the database row lock limits throughput, even when the web server shields it from crashing.")

if __name__ == "__main__":
    main()
