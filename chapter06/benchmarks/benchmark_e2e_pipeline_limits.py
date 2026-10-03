import os
import sys
import time
import threading
import requests
import redis
import uuid
import argparse
import concurrent.futures

# Django setup to easily create a test user
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../photoz')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bses.settings')
import django
django.setup()

from django.contrib.auth.models import User
from users.models import UserProfile

def parse_args():
    parser = argparse.ArgumentParser(description="End-to-End Benchmark: Redis Pipelining Limits impacting Web Traffic")
    parser.add_argument('--host', type=str, default='http://localhost', help='App server base URL (e.g. http://localhost or http://<alb-ip>)')
    parser.add_argument('--redis-host', type=str, default='localhost', help='Redis server host (e.g. localhost or <redis-ec2-ip>)')
    parser.add_argument('--redis-port', type=int, default=6379, help='Redis server port')
    parser.add_argument('--redis-db', type=int, default=1, help='Redis DB index')
    parser.add_argument('--pipeline-size', type=int, default=500000, help='Number of commands in the massive pipeline (simulates followers)')
    parser.add_argument('--concurrency', type=int, default=5, help='Number of concurrent Celery workers sending massive pipelines')
    return parser.parse_args()

def monitor_api_latency(session, url, stop_event, latencies):
    """
    Continuously fetches the newsfeed via HTTP.
    This simulates normal web traffic hitting the App Server.
    The App Server requires Redis to fetch the feed cache.
    """
    while not stop_event.is_set():
        start = time.time()
        try:
            res = session.get(url, timeout=10)
            status = res.status_code
        except Exception as e:
            status = f"TIMEOUT/ERROR: {str(e)}"
            
        duration = time.time() - start
        latencies.append((duration, status))
        time.sleep(0.1)

def build_and_execute_pipeline(worker_id, args):
    """Builds and executes a massive pipeline, simulating a Celery Fanout task."""
    client = redis.Redis(host=args.redis_host, port=args.redis_port, db=args.redis_db)
    photo_id = f"blocked_photo_{worker_id}"
    keys = [f":1:feed:dummy_celeb_{worker_id}_{i}" for i in range(args.pipeline_size)]
    
    pipeline = client.pipeline(transaction=False)
    for key in keys:
        pipeline.lpush(key, photo_id)
        
    try:
        pipeline.execute()
    except Exception:
        pass
        
    # Cleanup
    cleanup_pipeline = client.pipeline(transaction=False)
    for i, key in enumerate(keys):
        cleanup_pipeline.delete(key)
        if i > 0 and i % 10000 == 0:
            cleanup_pipeline.execute()
    cleanup_pipeline.execute()

def main():
    args = parse_args()
    base_url = args.host.rstrip('/')
    
    print(f"1. Creating dummy user for API testing...")
    test_username = f"e2e_tester_{uuid.uuid4().hex[:6]}"
    user = User.objects.create_user(username=test_username, password='password123')
    UserProfile.objects.create(user=user, username_display=test_username, first_name='E2E', last_name='Tester')
    
    print(f"2. Logging in via API to get session cookie...")
    session = requests.Session()
    login_url = f"{base_url}/users/login/"
    session.get(login_url)
    csrf_token = session.cookies.get('csrftoken')
    response = session.post(login_url, data={
        'username': test_username,
        'password': 'password123',
        'csrfmiddlewaretoken': csrf_token
    }, headers={'Referer': login_url})
    
    if response.status_code != 200 or 'Please enter a correct' in response.text:
        print(f"Login failed for {test_username}!")
        sys.exit(1)
        
    # Warm up the cache by hitting the newsfeed once
    newsfeed_url = f"{base_url}/"
    session.get(newsfeed_url)
    
    print(f"3. Starting background thread to constantly load the Newsfeed (simulating Web Traffic)...")
    stop_event = threading.Event()
    latencies = []
    monitor_thread = threading.Thread(target=monitor_api_latency, args=(session, newsfeed_url, stop_event, latencies))
    monitor_thread.start()
    
    # Wait a moment to gather baseline HTTP latency
    time.sleep(2)
    
    print(f"\n4. Simulating {args.concurrency} Celery workers executing massive fanout pipelines...")
    print(f"   Watch how the Redis block causes the HTTP requests to hang!")
    
    exec_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(build_and_execute_pipeline, i, args) for i in range(args.concurrency)]
        concurrent.futures.wait(futures)
        
    total_exec_time = time.time() - exec_start
    print(f"   Simulated Celery pipelines finished in {total_exec_time:.2f} seconds.")
    
    # Wait a tiny bit more for final HTTP requests to resolve
    time.sleep(1)
    stop_event.set()
    monitor_thread.join()
    
    # Analyze latencies
    baseline_latencies = [l[0] for l in latencies[:10]] # First 10 requests were during sleep
    avg_baseline = (sum(baseline_latencies) / len(baseline_latencies)) * 1000 if baseline_latencies else 0
    
    # Find the maximum latency and any errors
    max_latency_val = 0
    errors = 0
    for duration, status in latencies:
        if duration > max_latency_val:
            max_latency_val = duration
        if status != 200:
            errors += 1
            
    max_latency_ms = max_latency_val * 1000
    
    print("\n--- END-TO-END BOTTLENECK RESULTS ---")
    print(f"Simulated Celery Concurrency: {args.concurrency} workers")
    print(f"Pipeline Size: {args.pipeline_size} commands per worker")
    print(f"Total Background Operations: {args.concurrency * args.pipeline_size}")
    print(f"Normal HTTP Latency (Baseline): {avg_baseline:.2f} ms")
    print(f"Spike HTTP Latency (Blocked): {max_latency_ms:.2f} ms")
    print(f"Total HTTP Errors/Timeouts: {errors}")
    
    print("\n--- ANALYSIS ---")
    print("Because the synchronous Django Application Server requires a connection to Redis")
    print("to fetch the Newsfeed Cache, it is completely dependent on Redis's responsiveness.")
    print("When the background Celery Workers flood Redis with massive pipelines, the Redis")
    print("Event Loop blocks.")
    print(f"This caused standard HTTP traffic to hang for up to {max_latency_ms/1000:.2f} seconds!")
    print("If this block exceeds Gunicorn or Nginx's timeout, the web server will return a 502/504 Bad Gateway.")
    print("This proves that a poorly designed background task can take down the entire synchronous web application.")

if __name__ == "__main__":
    main()
