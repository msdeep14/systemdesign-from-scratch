import os
import sys
import time
import requests
import redis
import uuid
import argparse
import concurrent.futures
from io import BytesIO
from PIL import Image

# Parse DB args manually before django.setup() so settings.py picks them up
for i, arg in enumerate(sys.argv):
    if arg == '--db-host' and len(sys.argv) > i + 1:
        os.environ['POSTGRES_HOST'] = sys.argv[i+1]
    if arg == '--db-password' and len(sys.argv) > i + 1:
        os.environ['POSTGRES_PASSWORD'] = sys.argv[i+1]

# Django setup to easily seed the massive follower list
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../photoz')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bses.settings')
import django
django.setup()

from django.contrib.auth.models import User
from users.models import Follow, UserProfile
from newsfeed.services import CELEBRITY_FOLLOWER_THRESHOLD

def create_dummy_image():
    img = Image.new('RGB', (100, 100), color = 'blue')
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_byte_arr.seek(0)
    return img_byte_arr.read()

def main():
    parser = argparse.ArgumentParser(description="Celery Fanout Bottleneck Benchmark")
    parser.add_argument("--host", default="http://localhost", help="Base URL of Photoz (e.g. http://localhost or http://<alb-ip>)")
    parser.add_argument("--redis-host", default="localhost", help="Redis host (e.g. localhost or ElastiCache endpoint)")
    parser.add_argument("--db-host", help="Postgres DB host (required if testing against remote ALB from local laptop)")
    parser.add_argument("--db-password", help="Postgres DB password (required if testing against remote ALB)")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of concurrent power users to upload photos")
    args = parser.parse_args()
    
    base_url = args.host.rstrip('/')
    redis_client = redis.Redis(host=args.redis_host, port=6379, db=1)
    
    # We will test the maximum possible followers for a "normal" user before they 
    # cross the threshold and become a celebrity (which skips fanout).
    num_followers = CELEBRITY_FOLLOWER_THRESHOLD - 1
    
    print(f"1. Seeding {args.concurrency} Power Users with {num_followers} followers each...")
    uploaders = []
    for c in range(args.concurrency):
        uploader_username = f"power_user_{uuid.uuid4().hex[:6]}"
        django_username = str(uuid.uuid4())[:30]
        uploader = User.objects.create_user(username=django_username, password='password123')
        profile = UserProfile.objects.create(
            user=uploader,
            username_display=uploader_username,
            first_name='Power',
            last_name='User',
            follower_count=num_followers
        )
        uploaders.append((uploader_username, uploader))
        
    print(f"   Injecting {num_followers} dummy users to follow them... (This takes a moment)")
    dummy_users = [
        User(username=f"dummy_{i}_{uuid.uuid4().hex[:6]}")
        for i in range(num_followers)
    ]
    created_users = User.objects.bulk_create(dummy_users, batch_size=5000)
    
    print(f"   Injecting {args.concurrency * num_followers} follow edges...")
    follows = []
    for _, uploader in uploaders:
        for user in created_users:
            follows.append(Follow(following=uploader, follower=user))
            
    Follow.objects.bulk_create(follows, batch_size=10000)
    
    # The last follower's ID is what we'll monitor for each uploader
    last_follower_id = created_users[-1].id
    
    print(f"   Waiting 15 seconds for Postgres Read Replica to catch up to the 150k new follow edges...")
    time.sleep(15)
    
    print(f"2. Logging in via API...")
    sessions = []
    for uploader_username, _ in uploaders:
        session = requests.Session()
        login_url = f"{base_url}/users/login/"
        session.get(login_url)
        csrf_token = session.cookies.get('csrftoken')
        response = session.post(login_url, data={
            'username': uploader_username,
            'password': 'password123',
            'csrfmiddlewaretoken': csrf_token
        }, headers={'Referer': login_url})
        
        if response.status_code != 200 or 'Please enter a correct' in response.text:
            print(f"Login failed for {uploader_username}!")
            sys.exit(1)
        sessions.append((uploader_username, session))
    
    print(f"3. Uploading {args.concurrency} Photos Concurrently...")
    upload_url = f"{base_url}/photos/upload/"
    
    # We MUST clear and warm up the last follower's feed cache!
    last_follower_feed_key = f":1:feed:{last_follower_id}"
    redis_client.delete(last_follower_feed_key)
    redis_client.lpush(last_follower_feed_key, 0)
    
    def do_upload(args):
        username, session = args
        csrf_token = session.cookies.get('csrftoken')
        t0 = time.time()
        res = session.post(upload_url, data={
            'caption': f'Benchmarking {username}',
            'csrfmiddlewaretoken': csrf_token
        }, files={'image': ('bench.jpg', create_dummy_image(), 'image/jpeg')}, headers={'Referer': upload_url})
        return time.time() - t0, res

    upload_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(executor.map(do_upload, sessions))
        
    for t, res in results:
        if res.status_code != 200:
            print(f"An upload failed with status {res.status_code}!")
            sys.exit(1)
            
    upload_end = time.time()
    avg_upload_time = sum(t for t, res in results) / args.concurrency
    print(f"   Avg HTTP Upload took: {avg_upload_time:.2f} seconds.")
    print(f"   Total elapsed upload time: {upload_end - upload_start:.2f} seconds.")
    
    print(f"4. Monitoring Redis for {args.concurrency} fanouts to reach the {num_followers}th follower's feed...")
    fanout_start = upload_end
    
    while True:
        # We warmed it up with 1 dummy item, plus we expect args.concurrency new items
        if redis_client.llen(last_follower_feed_key) > args.concurrency:
            fanout_end = time.time()
            break
        time.sleep(0.1)
        
    fanout_time = fanout_end - fanout_start
    total_pushes = num_followers * args.concurrency
    
    print("\n--- BENCHMARK RESULTS ---")
    print(f"Total concurrent uploads: {args.concurrency}")
    print(f"Total followers fanned out to: {total_pushes}")
    print(f"Total time taken by Celery Workers: {fanout_time:.2f} seconds")
    print(f"Throughput: {total_pushes / fanout_time:.0f} Redis LPUSH operations per second\n")
    
    print("--- ANALYSIS ---")
    print("When concurrency > Celery workers, tasks will queue and 'Worker Starvation' gets exponentially worse.")
    print(f"It took {fanout_time:.2f} seconds to process {args.concurrency} uploads. Any regular user uploading")
    print("a photo during this window would have their feed generation completely stalled.")

if __name__ == "__main__":
    main()
