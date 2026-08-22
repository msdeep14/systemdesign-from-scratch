#!/usr/bin/env python3
"""
Benchmark: Repeated Disk Reads on a Read Replica.

What it measures:
    - Fires N sequential HTTP requests to the PhotoZ application for the
      same user's profile page and newsfeed.
    - After the requests, queries pg_stat_statements on the PRIMARY to count
      how many times each SQL statement was executed and total time spent.
    - Shows: N requests -> N identical DB queries -> N disk reads.

Usage (run locally via SSH tunnel):

    # Terminal 1: Open the tunnel to the primary DB
    # ssh -i key.pem -N -L 5432:127.0.0.1:5432 ubuntu@<db-public-ip>

    # Terminal 2: Run the script
    python chapter04/caching/benchmark_repeated_reads.py \
        --url http://<lb-public-ip> \
        --db-host 127.0.0.1 \
        --username test_user \
        --db-password <db_password> \
        --requests 30
"""

import argparse
import os
import re
import sys
import time

import psycopg2
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def login(session, base_url, username, password):
    login_url = f"{base_url}/users/login/"
    resp = session.get(login_url, timeout=15)
    if resp.status_code != 200:
        print(f"ERROR: Could not reach login page (status {resp.status_code})")
        return False

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
    time.sleep(1.5)
    if resp.status_code == 302:
        resp = session.get(f"{base_url}{resp.headers['Location']}")

    logged_in = resp.status_code == 200 and "/users/login/" not in resp.url
    if not logged_in:
        print(f"ERROR: Login failed. Status={resp.status_code}, URL={resp.url}")
    return logged_in


def reset_pg_stat_statements(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT pg_stat_statements_reset();")
    conn.commit()


def fetch_pg_stat_statements(conn, min_calls=5):
    """
    Return top statements by total execution time, filtering to those
    that fired at least min_calls times (to filter out noise).
    Only shows SELECT queries (reads).
    """
    query = """
        SELECT
            calls,
            round(total_exec_time::numeric, 2) AS total_ms,
            round(mean_exec_time::numeric, 2) AS avg_ms,
            round(min_exec_time::numeric, 2) AS min_ms,
            round(max_exec_time::numeric, 2) AS max_ms,
            left(query, 120) AS query_text
        FROM pg_stat_statements
        WHERE calls >= %s
          AND upper(ltrim(query)) LIKE 'SELECT%%'
        ORDER BY total_exec_time DESC
        LIMIT 15;
    """
    with conn.cursor() as cur:
        cur.execute(query, (min_calls,))
        return cur.fetchall()


def print_separator(char="-", width=100):
    print(char * width)


def run_repeated_reads(
    base_url,
    username,
    password,
    n_requests,
    db_host,
    db_port,
    db_name,
    db_user,
    db_password,
):
    print("\n" + "=" * 100)
    print("  BENCHMARK: Repeated Disk Reads (No Cache)")
    print("=" * 100)
    print(f"  Target:    {base_url}")
    print(f"  Requests:  {n_requests} sequential reads of the same pages")
    print(f"  DB host:   {db_host}:{db_port}")
    print()

    # Connect directly to the PRIMARY to read pg_stat_statements
    try:
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password,
            connect_timeout=10,
        )
    except Exception as e:
        print(f"ERROR: Could not connect to primary DB: {e}")
        print(
            "       Make sure --db-host points to the primary and port 5432 is reachable."
        )
        sys.exit(1)

    # Reset counters so we only measure this test run
    reset_pg_stat_statements(conn)
    print("  pg_stat_statements reset. Starting requests...\n")

    session = requests.Session()
    session.headers.update({"User-Agent": "PhotoZ-CacheBenchmark/1.0"})

    print(f"  Logging in as '{username}'...")
    if not login(session, base_url, username, password):
        print("  ERROR: Login failed. Is the database seeded?")
        conn.close()
        sys.exit(1)
    print("  Login OK.\n")

    # Find profile username to benchmark profile page
    resp = session.get(f"{base_url}/", timeout=15)
    profile_match = re.search(r"/users/profile/([^/\"]+)/", resp.text)
    profile_url = (
        f"{base_url}/users/profile/{profile_match.group(1)}/" if profile_match else None
    )

    newsfeed_url = f"{base_url}/"

    urls_to_hit = [("Newsfeed", newsfeed_url)]
    if profile_url:
        urls_to_hit.append(("Profile", profile_url))

    latencies = []
    print(f"  {'#':<5} {'Page':<12} {'Status':<8} {'Latency (ms)':<15}")
    print_separator()

    for i in range(1, n_requests + 1):
        for page_name, url in urls_to_hit:
            start = time.time()
            resp = session.get(url, timeout=15)
            elapsed_ms = (time.time() - start) * 1000
            latencies.append(elapsed_ms)
            print(f"  {i:<5} {page_name:<12} {resp.status_code:<8} {elapsed_ms:<15.1f}")

    print_separator()
    avg_latency = sum(latencies) / len(latencies)
    latencies_sorted = sorted(latencies)
    p95_latency = latencies_sorted[int(len(latencies_sorted) * 0.95)]
    print(f"\n  Avg latency: {avg_latency:.1f}ms   p95 latency: {p95_latency:.1f}ms\n")

    # Now read pg_stat_statements to show how many times each query ran
    print("\n" + "=" * 100)
    print("  pg_stat_statements RESULTS (SELECT queries, min 5 calls)")
    print("  These are the DB queries that fired during the above requests.")
    print("=" * 100)
    print()

    rows = fetch_pg_stat_statements(conn, min_calls=5)
    if not rows:
        print(
            "  No statements found. Check pg_stat_statements is enabled and the min_calls threshold."
        )
    else:
        header = f"  {'Calls':<8} {'Total(ms)':<12} {'Avg(ms)':<10} {'Min(ms)':<10} {'Max(ms)':<10} Query"
        print(header)
        print_separator()
        for row in rows:
            calls, total_ms, avg_ms, min_ms, max_ms, query_text = row
            query_text = query_text.replace("\n", " ").strip()
            print(
                f"  {calls:<8} {total_ms:<12} {avg_ms:<10} {min_ms:<10} {max_ms:<10} {query_text[:60]}..."
            )

    # Explicit Cache Verification
    print("\n" + "=" * 100)
    print("  CACHE VERIFICATION")
    print("=" * 100)

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

    print(f"  Total HTTP Requests made: {n_requests * len(urls_to_hit)}")
    print(f"  Heavy Feed Queries Executed (Cache Misses): {heavy_calls}")
    print(f"  Fast Pagination Queries Executed (Write-Around): {fast_calls}")
    print()

    if heavy_calls <= 1 and n_requests > 5:
        print(
            "  SUCCESS: Redis caching is active! The heavy feed calculation was skipped"
        )
        print(
            "     for almost all requests, falling back safely to fast pagination queries."
        )
    elif heavy_calls > 1:
        print(
            "  WARNING: The heavy feed query ran multiple times. Caching might be failing"
        )
        print("     or falling back to LocMemCache (per-worker cache).")

    conn.close()

    print("\n" + "=" * 100)
    print("  INTERPRETATION")
    print("=" * 100)
    print(f"""
        You made {n_requests} requests to {len(urls_to_hit)} page(s) = {n_requests * len(urls_to_hit)} total HTTP requests.
        Each 'calls' value in pg_stat_statements above shows how many times that
        SQL query ran against the database.""")


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark repeated disk reads to prove the cache justification"
    )
    parser.add_argument(
        "--url",
        default="http://localhost",
        help="Base URL of the PhotoZ app (default: http://localhost)",
    )
    parser.add_argument(
        "--username",
        default="test_user",
        help="Username to log in with (default: test_user)",
    )
    parser.add_argument(
        "--password", default="password123", help="Password (default: password123)"
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=30,
        help="Number of sequential requests to fire (default: 30)",
    )
    parser.add_argument(
        "--db-host",
        default="localhost",
        help="Primary DB host for pg_stat_statements (default: localhost)",
    )
    parser.add_argument(
        "--db-port", type=int, default=5432, help="Primary DB port (default: 5432)"
    )
    parser.add_argument(
        "--db-name",
        default=os.environ.get("POSTGRES_DB", "bses"),
        help="DB name (default: bses or POSTGRES_DB env var)",
    )
    parser.add_argument(
        "--db-user",
        default=os.environ.get("POSTGRES_USER", "postgres"),
        help="DB user (default: postgres or POSTGRES_USER env var)",
    )
    parser.add_argument(
        "--db-password",
        default=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        help="DB password (default: postgres or POSTGRES_PASSWORD env var)",
    )
    args = parser.parse_args()

    run_repeated_reads(
        base_url=args.url,
        username=args.username,
        password=args.password,
        n_requests=args.requests,
        db_host=args.db_host,
        db_port=args.db_port,
        db_name=args.db_name,
        db_user=args.db_user,
        db_password=args.db_password,
    )


if __name__ == "__main__":
    main()
