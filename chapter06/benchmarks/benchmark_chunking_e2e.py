import os
import sys
import time
import threading
import requests
import redis
import uuid
import argparse
import concurrent.futures
from io import BytesIO
from PIL import Image

for i, arg in enumerate(sys.argv):
    if arg == '--db-host' and len(sys.argv) > i + 1:
        os.environ['POSTGRES_HOST'] = sys.argv[i+1]
    if arg == '--db-password' and len(sys.argv) > i + 1:
        os.environ['POSTGRES_PASSWORD'] = sys.argv[i+1]

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../photoz')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bses.settings')
import django
django.setup()

from django.contrib.auth.models import User
from users.models import Follow, UserProfile
from newsfeed.services import CELEBRITY_FOLLOWER_THRESHOLD
from django.conf import settings

def create_dummy_image():
    img = Image.new('RGB', (100, 100), color = 'green')
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_byte_arr.seek(0)
    return img_byte_arr.read()

def monitor_api_latency(session, url, stop_event, latencies):
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

def main():
    parser = argparse.ArgumentParser(description="End-to-End Benchmark: Celery Chunking Validation")
    parser.add_argument("--host", default="http://localhost", help="Base URL of Photoz")
    parser.add_argument("--redis-host", default="localhost", help="Redis host")
    parser.add_argument("--db-host", help="Postgres DB host")
    parser.add_argument("--db-password", help="Postgres DB password")
    parser.add_argument("--concurrency", type=int, default=1, help="Concurrent uploads")
    args = parser.parse_args()
    
    base_url = args.host.rstrip('/')
    redis_client = redis.Redis(host=args.redis_host, port=6379, db=1)
    
    num_followers = CELEBRITY_FOLLOWER_THRESHOLD - 1
    
    print(f"1. Seeding {args.concurrency} Power Users with {num_followers} followers each...")
    uploaders = []
    for c in range(args.concurrency):
        uploader_username = f"power_user_{uuid.uuid4().hex[:6]}"
        django_username = str(uuid.uuid4())[:30]
        uploader = User.objects.create_user(username=django_username, password='password123')
        UserProfile.objects.create(user=uploader, username_display=uploader_username, first_name='Power', last_name='User', follower_count=num_followers)
        uploaders.append((uploader_username, uploader))
        
    print(f"   Injecting {num_followers} dummy users to follow them... (Takes a moment)")
    dummy_users = [User(username=f"dummy_{i}_{uuid.uuid4().hex[:6]}") for i in range(num_followers)]
    created_users = User.objects.bulk_create(dummy_users, batch_size=5000)
    
    print(f"   Injecting {args.concurrency * num_followers} follow edges...")
    follows = []
    for _, uploader in uploaders:
        for user in created_users:
            follows.append(Follow(following=uploader, follower=user))
    Follow.objects.bulk_create(follows, batch_size=10000)
    
    last_follower_id = created_users[-1].id
    
    print(f"   Waiting 15 seconds for Postgres Read Replica to catch up...")
    time.sleep(15)
    
    print(f"2. Logging in via API...")
    sessions = []
    for uploader_username, _ in uploaders:
        session = requests.Session()
        login_url = f"{base_url}/users/login/"
        session.get(login_url)
        csrf_token = session.cookies.get('csrftoken')
        response = session.post(login_url, data={'username': uploader_username, 'password': 'password123', 'csrfmiddlewaretoken': csrf_token}, headers={'Referer': login_url})
        if response.status_code != 200:
            print("Login failed!")
            sys.exit(1)
        sessions.append((uploader_username, session))
    
    newsfeed_url = f"{base_url}/"
    sessions[0][1].get(newsfeed_url)
    
    print(f"3. Starting background thread to constantly load the Newsfeed (simulating Web Traffic)...")
    stop_event = threading.Event()
    latencies = []
    monitor_thread = threading.Thread(target=monitor_api_latency, args=(sessions[0][1], newsfeed_url, stop_event, latencies))
    monitor_thread.start()
    
    time.sleep(2)
    
    print(f"\n4. Uploading {args.concurrency} Photos Concurrently via real API (Triggering Celery Canvas)...")
    upload_url = f"{base_url}/photos/upload/"
    
    last_follower_feed_key = f":1:feed:{last_follower_id}"
    redis_client.delete(last_follower_feed_key)
    redis_client.lpush(last_follower_feed_key, 0)
    
    def do_upload(args):
        username, session = args
        csrf_token = session.cookies.get('csrftoken')
        return session.post(upload_url, data={'caption': f'Chunking Test', 'csrfmiddlewaretoken': csrf_token}, files={'image': ('chunk.jpg', create_dummy_image(), 'image/jpeg')}, headers={'Referer': upload_url})

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(executor.map(do_upload, sessions))
        
    print(f"   Waiting for Celery to fanout to all {num_followers} followers in chunks of {settings.FANOUT_PIPELINE_CHUNK_SIZE}...")
    while True:
        if redis_client.llen(last_follower_feed_key) > args.concurrency:
            break
        time.sleep(0.1)
    
    time.sleep(1)
    stop_event.set()
    monitor_thread.join()
    
    baseline_latencies = [l[0] for l in latencies[:10]]
    avg_baseline = (sum(baseline_latencies) / len(baseline_latencies)) * 1000 if baseline_latencies else 0
    max_latency_val = max([l[0] for l in latencies])
    
    print("\n--- CHUNKING E2E BENCHMARK RESULTS ---")
    print(f"Concurrent Photo Uploads: {args.concurrency}")
    print(f"Total Followers: {args.concurrency * num_followers}")
    print(f"Celery Chunk Size: {settings.FANOUT_PIPELINE_CHUNK_SIZE}")
    print(f"Normal HTTP Latency (Baseline): {avg_baseline:.2f} ms")
    print(f"Spike HTTP Latency (During Fanout): {max_latency_val * 1000:.2f} ms")
    
    print("\n--- ANALYSIS ---")
    if (max_latency_val * 1000) > (avg_baseline + 200):
        print("WARNING: Latency spiked! Redis event loop might still be blocked, or the app server struggled.")
    else:
        print("SUCCESS! By orchestrating Celery to dispatch 1,000-command chunks instead of monolithic pipelines,")
        print("the Redis Event Loop is no longer blocked. HTTP web traffic remained fast and responsive while the")
        print("background fanout successfully completed.")

if __name__ == "__main__":
    main()
