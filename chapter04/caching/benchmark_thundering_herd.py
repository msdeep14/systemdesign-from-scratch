#!/usr/bin/env python3
"""
Benchmark: Thundering Herd on Cache Miss

What it measures:
    - Clears the Redis cache for the target user to guarantee a cache miss.
    - Fires N CONCURRENT HTTP requests to the PhotoZ newsfeed.
    - Queries pg_stat_statements on the PRIMARY to count how many times the
      heavy feed generation query was executed.
    - Shows: If N concurrent requests -> N heavy DB queries, you have a Thundering Herd.
      If N concurrent requests -> 1 heavy DB query (and N-1 waits), you fixed it.

Usage (run locally via SSH tunnels):

    # Terminal 1: Open tunnel to primary DB
    # ssh -i key.pem -N -L 5432:127.0.0.1:5432 ubuntu@<db-public-ip>
    
    # Terminal 2: Open tunnel to Redis
    # ssh -i key.pem -N -L 6379:127.0.0.1:6379 ubuntu@<redis-public-ip>

    # Terminal 3: Run the script
    python chapter04/caching/benchmark_thundering_herd.py \
        --url http://<lb-public-ip> \
        --db-host 127.0.0.1 \
        --redis-host 127.0.0.1 \
        --username test_user \
        --db-password postgres \
        --concurrency 50
"""

import argparse
import os
import re
import sys
import time
import concurrent.futures

import psycopg2
import redis
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def login(base_url, username, password):
    session = requests.Session()
    session.headers.update({"User-Agent": "PhotoZ-ThunderingHerd/1.0"})
    
    login_url = f"{base_url}/users/login/"
    resp = session.get(login_url, timeout=15)
    if resp.status_code != 200:
        print(f"ERROR: Could not reach login page (status {resp.status_code})")
        return None

    csrf_token = session.cookies.get("csrftoken", "")
    if not csrf_token:
        match = re.search(
            r"name=[\"']csrfmiddlewaretoken[\"'] value=[\"']([^\"']+)", resp.text
        )
        if match:
            csrf_token = match.group(1)

    resp = session.post(
        login_url,
        data={
            "username": username,
            "password": password,
            "csrfmiddlewaretoken": csrf_token,
        },
        headers={"Referer": login_url},
        timeout=15,
        allow_redirects=False,
    )
    if resp.status_code == 302:
        resp = session.get(f"{base_url}{resp.headers['Location']}")

    logged_in = resp.status_code == 200 and "/users/login/" not in resp.url
    if not logged_in:
        print(f"ERROR: Login failed. Status={resp.status_code}, URL={resp.url}")
        return None
    return session


def reset_pg_stat_statements(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT pg_stat_statements_reset();")
    conn.commit()


def get_user_id(conn, username):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM auth_user WHERE username = %s;", (username,))
        row = cur.fetchone()
        return row[0] if row else None


def fetch_cache_stats(conn):
    with conn.cursor() as cur:
        # Check heavy feed query (looking for ORDER BY created_at)
        cur.execute("""
            SELECT SUM(calls) FROM pg_stat_statements 
            WHERE upper(query) LIKE '%PHOTOS_PHOTO%' 
            AND upper(query) LIKE '%ORDER BY%CREATED_AT%DESC%'
        """)
        heavy_calls = cur.fetchone()[0] or 0
        
        # Check fast pagination query (looking for WHERE id IN (...))
        cur.execute("""
            SELECT SUM(calls) FROM pg_stat_statements 
            WHERE upper(query) LIKE 'SELECT%PHOTOS_PHOTO%WHERE%ID%IN%'
        """)
        fast_calls = cur.fetchone()[0] or 0
        return heavy_calls, fast_calls


def fetch_url(session, url, request_id):
    start = time.time()
    try:
        resp = session.get(url, timeout=30)
        elapsed_ms = (time.time() - start) * 1000
        return request_id, resp.status_code, elapsed_ms
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000
        return request_id, str(e), elapsed_ms


def print_separator(char="-", width=100):
    print(char * width)


def run_benchmark(base_url, username, password, concurrency, db_host, db_port, db_name, db_user, db_password, redis_host, redis_port):
    print("\n" + "=" * 100)
    print("  BENCHMARK: Thundering Herd (Concurrent Cache Misses)")
    print("=" * 100)
    print(f"  Target:       {base_url}")
    print(f"  Concurrency:  {concurrency} simultaneous requests to the same feed")
    print(f"  DB host:      {db_host}:{db_port}")
    print(f"  Redis host:   {redis_host}:{redis_port}")
    print()

    # 1. Connect to DB
    try:
        conn = psycopg2.connect(
            host=db_host, port=db_port, dbname=db_name,
            user=db_user, password=db_password, connect_timeout=10,
        )
    except Exception as e:
        print(f"ERROR: Could not connect to primary DB: {e}")
        sys.exit(1)

    # 2. Get User ID for cache key mapping
    user_id = get_user_id(conn, username)
    if not user_id:
        print(f"ERROR: User '{username}' not found in DB.")
        sys.exit(1)
        
    cache_key = f":1:feed:{user_id}"

    # 3. Connect to Redis and Clear Cache
    try:
        r = redis.Redis(host=redis_host, port=redis_port, db=1)
        r.ping()
        r.delete(cache_key)
        print(f"  [REDIS] Successfully cleared cache key: {cache_key}")
    except Exception as e:
        print(f"ERROR: Could not connect to Redis or clear cache: {e}")
        print("       Is the SSH tunnel to Redis on port 6379 open? Run: pip install redis")
        sys.exit(1)

    # 4. Login once to get the session cookie
    print(f"  [HTTP] Logging in as '{username}'...")
    session = login(base_url, username, password)
    if not session:
        sys.exit(1)
    print("  [HTTP] Login OK.\n")

    # 5. Reset DB stats
    reset_pg_stat_statements(conn)
    print("  [DB] pg_stat_statements reset.")
    
    # Wait a few seconds to let any Read-Your-Writes middleware lock expire 
    # (so we don't accidentally force all requests to primary due to the login POST)
    print("  [WAIT] Sleeping for 6 seconds to let Read-Your-Writes lock expire...")
    time.sleep(6)

    # 6. Fire Concurrent Requests
    newsfeed_url = f"{base_url}/"
    print(f"\n  FIRING {concurrency} CONCURRENT REQUESTS TO {newsfeed_url}...\n")
    
    start_time = time.time()
    results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(fetch_url, session, newsfeed_url, i) 
            for i in range(concurrency)
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            
    total_time = time.time() - start_time
    print(f"  Finished {concurrency} requests in {total_time:.2f} seconds.")

    # Sort results by ID
    results.sort(key=lambda x: x[0])
    
    latencies = [res[2] for res in results]
    successes = len([res for res in results if res[1] == 200])
    
    print(f"  Successful requests (HTTP 200): {successes}/{concurrency}")
    print(f"  Avg latency: {sum(latencies)/len(latencies):.1f} ms | Max latency: {max(latencies):.1f} ms\n")

    # 7. Check DB Stats (The Thundering Herd Verification)
    print("=" * 100)
    print("  CACHE VERIFICATION (pg_stat_statements)")
    print("=" * 100)
    
    heavy_calls, fast_calls = fetch_cache_stats(conn)
    
    print(f"  Concurrent HTTP Requests made: {concurrency}")
    print(f"  Heavy Feed Queries Executed:   {heavy_calls}")
    print()
    
    if heavy_calls >= (concurrency * 0.5):
        print("  [ERROR] THUNDERING HERD DETECTED")
        print(f"     The database was hammered with {heavy_calls} identical heavy queries")
        print("     at the exact same time because everyone missed the cache simultaneously!")
    elif heavy_calls <= 2 and heavy_calls > 0:
        print("  [SUCCESS] CACHE PROMISE WORKING")
        print(f"     Despite {concurrency} concurrent requests missing the cache, the heavy")
        print(f"     query only executed {heavy_calls} time(s). The other requests waited for the promise.")
    elif heavy_calls == 0:
        print("  [WARNING] The heavy query didn't run at all. Did the cache clear fail?")
    else:
        print(f"  [WARNING] Mixed results. Heavy queries ran {heavy_calls} times.")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Benchmark Thundering Herd caching issue")
    parser.add_argument("--url", default="http://localhost")
    parser.add_argument("--username", default="test_user")
    parser.add_argument("--password", default="password123")
    parser.add_argument("--concurrency", type=int, default=50,
                        help="Number of concurrent requests (default: 50)")
    parser.add_argument("--db-host", default="localhost")
    parser.add_argument("--db-port", type=int, default=5432)
    parser.add_argument("--db-name", default=os.environ.get("POSTGRES_DB", "bses"))
    parser.add_argument("--db-user", default=os.environ.get("POSTGRES_USER", "postgres"))
    parser.add_argument("--db-password", default=os.environ.get("POSTGRES_PASSWORD", "postgres"))
    parser.add_argument("--redis-host", default="localhost",
                        help="Redis host to clear cache (default: localhost)")
    parser.add_argument("--redis-port", type=int, default=6379)
    args = parser.parse_args()

    run_benchmark(
        base_url=args.url,
        username=args.username,
        password=args.password,
        concurrency=args.concurrency,
        db_host=args.db_host,
        db_port=args.db_port,
        db_name=args.db_name,
        db_user=args.db_user,
        db_password=args.db_password,
        redis_host=args.redis_host,
        redis_port=args.redis_port,
    )


if __name__ == "__main__":
    main()
