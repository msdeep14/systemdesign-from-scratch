#!/usr/bin/env python3
"""
HTTP load test for the PhotoZ application.

Simulates concurrent users hitting the full request flow:
    Load Balancer (nginx) -> App Servers (gunicorn) -> Database (postgres)

Measures read and write latency, throughput, and HTTP errors to expose the
single-database-instance bottleneck under load.

Requires: pip install requests psycopg2-binary
Requires: Seeded database (run seed_data.py first)
"""

import argparse
import json
import os
import random
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock

import requests

try:
    import psycopg2
except ImportError:
    psycopg2 = None

# Disable SSL warnings for local testing
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


class MetricsCollector:
    """Thread-safe collector for request latency and error metrics."""

    def __init__(self):
        self._lock = Lock()
        self.results = []
        self.errors = []
        self.start_time = None
        self.end_time = None

    def record(self, category, endpoint, latency_ms, status_code):
        with self._lock:
            self.results.append(
                {
                    "category": category,
                    "endpoint": endpoint,
                    "latency_ms": latency_ms,
                    "status_code": status_code,
                    "timestamp": time.time(),
                }
            )

    def record_error(self, category, endpoint, error_msg):
        with self._lock:
            self.errors.append(
                {
                    "category": category,
                    "endpoint": endpoint,
                    "error": error_msg,
                    "timestamp": time.time(),
                }
            )

    def summary(self):
        duration = (
            self.end_time - self.start_time if self.end_time and self.start_time else 1
        )

        if not self.results:
            return {
                "duration_seconds": round(duration, 1),
                "total_requests": 0,
                "total_errors": len(self.errors),
                "reads": {},
                "writes": {},
                "by_endpoint": {},
            }

        reads = [r for r in self.results if r["category"] == "read"]
        writes = [r for r in self.results if r["category"] == "write"]

        def calc_stats(records):
            if not records:
                return {
                    "count": 0,
                    "avg_ms": 0,
                    "p50_ms": 0,
                    "p95_ms": 0,
                    "p99_ms": 0,
                    "rps": 0,
                    "errors_5xx": 0,
                }
            latencies = [r["latency_ms"] for r in records]
            latencies.sort()
            return {
                "count": len(records),
                "avg_ms": round(statistics.mean(latencies), 1),
                "p50_ms": round(latencies[len(latencies) // 2], 1),
                "p95_ms": round(latencies[int(len(latencies) * 0.95)], 1),
                "p99_ms": round(latencies[int(len(latencies) * 0.99)], 1),
                "rps": round(len(records) / duration, 1),
                "errors_5xx": sum(1 for r in records if r["status_code"] >= 500),
            }

        return {
            "duration_seconds": round(duration, 1),
            "total_requests": len(self.results),
            "total_errors": len(self.errors),
            "reads": calc_stats(reads),
            "writes": calc_stats(writes),
            "by_endpoint": {
                ep: calc_stats([r for r in self.results if r["endpoint"] == ep])
                for ep in set(r["endpoint"] for r in self.results)
            },
        }


# ---------------------------------------------------------------------------
# User session: handles login, CSRF, and request execution
# ---------------------------------------------------------------------------


class UserSession:
    """Simulates a single logged-in user making HTTP requests."""

    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "PhotoZ-LoadTest/1.0"})
        self.logged_in = False

    def login(self):
        login_url = f"{self.base_url}/users/login/"
        resp, _ = self.get("/users/login/")
        if resp.status_code != 200:
            return False

        csrf_token = self.session.cookies.get("csrftoken", "")
        if not csrf_token:
            match = re.search(
                r'name=["\']csrfmiddlewaretoken["\'] value=["\']([^"\']+)', resp.text
            )
            if match:
                csrf_token = match.group(1)

        resp = self.session.post(
            login_url,
            data={
                "username": self.username,
                "password": self.password,
                "csrfmiddlewaretoken": csrf_token,
            },
            headers={"Referer": login_url},
            timeout=30,
            allow_redirects=True,
        )
        self.logged_in = resp.status_code == 200 and "/users/login/" not in resp.url
        return self.logged_in

    def get(self, path):
        url = f"{self.base_url}{path}"
        start = time.time()
        resp = self.session.get(url, timeout=30, allow_redirects=True)
        latency_ms = (time.time() - start) * 1000
        return resp, latency_ms

    def post_ajax(self, path, data=None):
        url = f"{self.base_url}{path}"
        csrf_token = self.session.cookies.get("csrftoken", "")
        headers = {
            "X-CSRFToken": csrf_token,
            "Referer": self.base_url + "/",
            "X-Requested-With": "XMLHttpRequest",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data)
        else:
            body = None

        start = time.time()
        resp = self.session.post(
            url, data=body, headers=headers, timeout=30, allow_redirects=True
        )
        latency_ms = (time.time() - start) * 1000
        return resp, latency_ms


# ---------------------------------------------------------------------------
# Data discovery: find valid usernames and photo IDs for load testing
# ---------------------------------------------------------------------------


def discover_test_data(base_url):
    """Fetch sample usernames and photo IDs from the running application.

    Logs in as test_user, scrapes the newsfeed for photo IDs and profile
    links, and returns a dict of data needed by the workers.
    """
    print("  Discovering test data from the running application...")

    session = UserSession(base_url, "test_user", "password123")
    if not session.login():
        print("  ERROR: Could not log in as test_user. Is the database seeded?")
        sys.exit(1)

    # Get newsfeed page to find photo IDs and usernames
    resp, _ = session.get("/")
    photo_ids = re.findall(r"/photos/(\d+)/", resp.text)
    photo_ids = list(set(int(pid) for pid in photo_ids))

    usernames = re.findall(r'/users/([^/"]+)/', resp.text)
    # Filter out known non-username paths
    excluded = {"login", "logout", "signup", "search"}
    usernames = list(
        set(u for u in usernames if u not in excluded and "/edit" not in u)
    )

    if not photo_ids:
        print("  WARNING: No photo IDs found on newsfeed. Trying profile page...")
        resp, _ = session.get("/users/test_user/")
        photo_ids = re.findall(r"/photos/(\d+)/", resp.text)
        photo_ids = list(set(int(pid) for pid in photo_ids))

    if not photo_ids:
        print("  ERROR: No photo IDs found. Is the database seeded with photos?")
        sys.exit(1)

    print(f"  Found {len(photo_ids)} photo IDs, {len(usernames)} usernames")

    return {
        "photo_ids": photo_ids,
        "usernames": usernames if usernames else ["test_user"],
    }


# ---------------------------------------------------------------------------
# Worker functions
# ---------------------------------------------------------------------------


def generate_usernames(count):
    """Generate a list of seeded usernames to use for login.

    The seed script creates users with pattern: {first}_{last}_{index}.
    Index 0 is test_user. We use indices 1 through count.
    """
    first_names = [
        "alex",
        "jordan",
        "taylor",
        "morgan",
        "casey",
        "riley",
        "avery",
        "quinn",
        "harper",
        "blake",
        "drew",
        "sage",
        "rowan",
        "river",
        "phoenix",
        "skyler",
        "cameron",
        "dakota",
        "emerson",
        "finley",
        "hayden",
        "jamie",
        "kendall",
        "logan",
        "micah",
        "noel",
        "parker",
        "reese",
        "sawyer",
        "tatum",
    ]
    last_names = [
        "smith",
        "johnson",
        "williams",
        "brown",
        "jones",
        "garcia",
        "miller",
        "davis",
        "rodriguez",
        "martinez",
        "wilson",
        "anderson",
        "thomas",
        "jackson",
        "white",
        "harris",
        "martin",
        "thompson",
        "moore",
        "young",
    ]
    # The seed script uses random.choice for first/last names, so we cannot
    # predict exact usernames. We generate a large pool and try them.
    # The workers will attempt login and skip if it fails.
    usernames = ["test_user"]
    for i in range(1, count + 1):
        first = random.choice(first_names)
        last = random.choice(last_names)
        usernames.append(f"{first}_{last}_{i}")
    return usernames


def read_worker(worker_id, base_url, test_data, collector, duration, stop_event):
    """Simulates a user repeatedly loading read-heavy pages."""
    time.sleep(random.uniform(0.1, 5.0))  # Jitter to prevent thundering herd on login
    username = (
        random.choice(test_data["usernames"]) if test_data["usernames"] else "test_user"
    )
    session = UserSession(base_url, username, "password123")

    if not session.login():
        collector.record_error(
            "read", "/users/login/", f"Worker {worker_id}: login failed"
        )
        return

    endpoints = ["/"]
    for uname in random.sample(
        test_data["usernames"], min(3, len(test_data["usernames"]))
    ):
        endpoints.append(f"/users/{uname}/")
    endpoints.append("/photos/search/?q=alex")

    deadline = time.time() + duration
    while time.time() < deadline and not stop_event.is_set():
        endpoint = random.choice(endpoints)
        try:
            resp, latency_ms = session.get(endpoint)
            collector.record("read", endpoint, latency_ms, resp.status_code)
        except requests.RequestException as e:
            collector.record_error("read", endpoint, str(e))


def write_worker(worker_id, base_url, test_data, collector, duration, stop_event):
    """Simulates a user repeatedly liking photos and adding comments."""
    time.sleep(random.uniform(0.1, 5.0))  # Jitter to prevent thundering herd on login
    username = (
        random.choice(test_data["usernames"]) if test_data["usernames"] else "test_user"
    )
    session = UserSession(base_url, username, "password123")

    if not session.login():
        collector.record_error(
            "write", "/users/login/", f"Worker {worker_id}: login failed"
        )
        return

    photo_ids = test_data["photo_ids"]
    comment_texts = [
        "Nice photo!",
        "Love this!",
        "Stunning!",
        "Amazing shot!",
        "So beautiful!",
        "Great capture!",
        "Incredible!",
        "Loving System Design From Scratch!",
    ]

    deadline = time.time() + duration
    while time.time() < deadline and not stop_event.is_set():
        photo_id = random.choice(photo_ids)
        action = random.choice(["like", "comment"])

        try:
            if action == "like":
                endpoint = f"/photos/{photo_id}/like/"
                resp, latency_ms = session.post_ajax(endpoint)
                collector.record("write", endpoint, latency_ms, resp.status_code)
            else:
                endpoint = f"/photos/{photo_id}/comment/"
                resp, latency_ms = session.post_ajax(
                    endpoint, data={"text": random.choice(comment_texts)}
                )
                collector.record("write", endpoint, latency_ms, resp.status_code)
        except requests.RequestException as e:
            collector.record_error("write", endpoint, str(e))


# ---------------------------------------------------------------------------
# DB stats (optional, requires direct DB access)
# ---------------------------------------------------------------------------


def get_db_connection_count(db_host, db_port, db_user, db_password, db_name):
    """Query PostgreSQL for the current number of active connections."""
    if psycopg2 is None:
        return None
    try:
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            dbname=db_name,
            connect_timeout=3,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
            active = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM pg_stat_activity")
            total = cur.fetchone()[0]
            cur.execute("SHOW max_connections")
            max_conn = int(cur.fetchone()[0])
        conn.close()
        return {"active": active, "total": total, "max": max_conn}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def print_results(summary, db_stats_before, db_stats_after):
    print("\n" + "=" * 70)
    print("  LOAD TEST RESULTS")
    print("=" * 70)

    print(f"\n  Duration:         {summary['duration_seconds']}s")
    print(f"  Total requests:   {summary['total_requests']}")
    print(f"  Connection errors:{summary['total_errors']}")

    print("\n  " + "-" * 66)
    print(f"  {'':30} {'READS':>15} {'WRITES':>15}")
    print("  " + "-" * 66)

    reads = summary.get("reads", {})
    writes = summary.get("writes", {})

    rows = [
        ("Requests", "count"),
        ("Avg latency (ms)", "avg_ms"),
        ("p50 latency (ms)", "p50_ms"),
        ("p95 latency (ms)", "p95_ms"),
        ("p99 latency (ms)", "p99_ms"),
        ("Requests/sec", "rps"),
        ("5xx errors", "errors_5xx"),
    ]
    for label, key in rows:
        r_val = reads.get(key, "N/A")
        w_val = writes.get(key, "N/A")
        print(f"  {label:30} {r_val!s:>15} {w_val!s:>15}")

    print("  " + "-" * 66)

    # Per-endpoint breakdown
    by_ep = summary.get("by_endpoint", {})
    if by_ep:
        print("\n  Per-endpoint breakdown:")
        print("  " + "-" * 66)
        print(
            f"  {'Endpoint':40} {'Count':>6} {'Avg(ms)':>8} {'p95(ms)':>8} {'5xx':>5}"
        )
        print("  " + "-" * 66)
        for ep, stats in sorted(by_ep.items()):
            ep_display = ep if len(ep) <= 38 else ep[:35] + "..."
            print(
                f"  {ep_display:40} {stats['count']:>6} {stats['avg_ms']:>8} {stats['p95_ms']:>8} {stats['errors_5xx']:>5}"
            )
        print("  " + "-" * 66)

    # DB connection stats
    if db_stats_before or db_stats_after:
        print("\n  PostgreSQL connection stats:")
        print("  " + "-" * 66)
        if db_stats_before:
            print(
                f"  Before test: {db_stats_before['total']} connections "
                f"({db_stats_before['active']} active) / max {db_stats_before['max']}"
            )
        if db_stats_after:
            print(
                f"  During test: {db_stats_after['total']} connections "
                f"({db_stats_after['active']} active) / max {db_stats_after['max']}"
            )
        print("  " + "-" * 66)

    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="HTTP load test for PhotoZ application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test against local Docker setup
  python benchmark_db_load.py --target http://localhost --concurrency 30 --duration 30

  # Test against EC2 load balancer
  python benchmark_db_load.py --target http://54.123.45.67 --concurrency 50 --duration 60

  # Save results for later comparison
  python benchmark_db_load.py --target http://localhost --save-to baseline.json
        """,
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Base URL of the load balancer (e.g. http://localhost or http://<LB_IP>)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=30,
        help="Total number of concurrent simulated users (default: 30)",
    )
    parser.add_argument(
        "--read-ratio",
        type=float,
        default=0.7,
        help="Fraction of workers doing reads vs writes (default: 0.7 = 70%% reads)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Duration of the test in seconds (default: 30)",
    )
    parser.add_argument(
        "--save-to", help="Save results to a JSON file for later comparison"
    )
    parser.add_argument(
        "--compare", help="Path to a baseline JSON file to compare against"
    )
    parser.add_argument(
        "--db-host",
        default=os.environ.get("POSTGRES_HOST", "localhost"),
        help="PostgreSQL host for connection stats (default: localhost)",
    )
    parser.add_argument(
        "--db-port",
        type=int,
        default=int(os.environ.get("POSTGRES_PORT", "5432")),
        help="PostgreSQL port (default: 5432)",
    )
    parser.add_argument(
        "--db-user",
        default=os.environ.get("POSTGRES_USER", "postgres"),
    )
    parser.add_argument(
        "--db-password",
        default=os.environ.get("POSTGRES_PASSWORD", "postgres"),
    )
    parser.add_argument(
        "--db-name",
        default=os.environ.get("POSTGRES_DB", "bses"),
    )

    args = parser.parse_args()

    num_readers = int(args.concurrency * args.read_ratio)
    num_writers = args.concurrency - num_readers

    print("\n" + "=" * 70)
    print("  PhotoZ HTTP Load Test")
    print("=" * 70)
    print(f"  Target:       {args.target}")
    print(
        f"  Concurrency:  {args.concurrency} ({num_readers} readers, {num_writers} writers)"
    )
    print(f"  Duration:     {args.duration}s")
    print(f"  Read ratio:   {args.read_ratio}")

    # Verify the target is reachable
    print("\n  Checking target is reachable...", end="", flush=True)
    try:
        resp = requests.get(f"{args.target}/users/login/", timeout=10)
        if resp.status_code != 200:
            print(f" FAILED (status {resp.status_code})")
            sys.exit(1)
        print(" OK")
    except requests.RequestException as e:
        print(f" FAILED ({e})")
        sys.exit(1)

    # Discover test data
    test_data = discover_test_data(args.target)

    # DB stats before
    db_stats_before = get_db_connection_count(
        args.db_host, args.db_port, args.db_user, args.db_password, args.db_name
    )
    if db_stats_before:
        print(
            f"  DB connections before test: {db_stats_before['total']} / {db_stats_before['max']}"
        )
    else:
        print("  DB connection stats: unavailable (direct DB access not configured)")

    # Run load test
    collector = MetricsCollector()

    stop_event = threading.Event()

    print(f"\n  Starting load test ({args.duration}s)...")
    collector.start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = []

        for i in range(num_readers):
            futures.append(
                executor.submit(
                    read_worker,
                    i,
                    args.target,
                    test_data,
                    collector,
                    args.duration,
                    stop_event,
                )
            )

        for i in range(num_writers):
            futures.append(
                executor.submit(
                    write_worker,
                    num_readers + i,
                    args.target,
                    test_data,
                    collector,
                    args.duration,
                    stop_event,
                )
            )

        # Sample DB connections during the test
        db_stats_during = None
        try:
            time.sleep(min(5, args.duration // 2))
            db_stats_during = get_db_connection_count(
                args.db_host, args.db_port, args.db_user, args.db_password, args.db_name
            )
        except Exception:
            pass

        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"  Worker error: {e}")

    collector.end_time = time.time()
    stop_event.set()

    # Results
    summary = collector.summary()
    print_results(summary, db_stats_before, db_stats_during)

    # Save results
    if args.save_to:
        output = {
            "timestamp": datetime.now().isoformat(),
            "target": args.target,
            "concurrency": args.concurrency,
            "read_ratio": args.read_ratio,
            "duration": args.duration,
            "summary": summary,
            "db_stats_before": db_stats_before,
            "db_stats_during": db_stats_during,
        }
        with open(args.save_to, "w") as f:
            json.dump(output, f, indent=2)
        print(f"  Results saved to {args.save_to}")

    # Compare with baseline
    if args.compare:
        print_comparison(args.compare, summary)


def print_comparison(baseline_path, current_summary):
    """Print a side-by-side comparison of baseline vs current results."""
    try:
        with open(baseline_path) as f:
            baseline = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  Could not load baseline: {e}")
        return

    baseline_summary = baseline.get("summary", {})

    print("\n" + "=" * 70)
    print("  COMPARISON: Baseline vs Current")
    print("=" * 70)
    print(
        f"  Baseline: {baseline.get('timestamp', 'unknown')} "
        f"(concurrency={baseline.get('concurrency', '?')})"
    )
    print()

    print(f"  {'Metric':30} {'Baseline':>12} {'Current':>12} {'Change':>12}")
    print("  " + "-" * 70)

    comparisons = [
        ("Read count", "reads", "count"),
        ("Read avg (ms)", "reads", "avg_ms"),
        ("Read p95 (ms)", "reads", "p95_ms"),
        ("Read p99 (ms)", "reads", "p99_ms"),
        ("Read rps", "reads", "rps"),
        ("Read 5xx", "reads", "errors_5xx"),
        ("Write count", "writes", "count"),
        ("Write avg (ms)", "writes", "avg_ms"),
        ("Write p95 (ms)", "writes", "p95_ms"),
        ("Write rps", "writes", "rps"),
        ("Write 5xx", "writes", "errors_5xx"),
    ]

    for label, category, key in comparisons:
        b_val = baseline_summary.get(category, {}).get(key, 0)
        c_val = current_summary.get(category, {}).get(key, 0)

        if b_val and b_val != 0:
            pct = ((c_val - b_val) / b_val) * 100
            change_str = f"{pct:+.1f}%"
        else:
            change_str = "N/A"

        print(f"  {label:30} {b_val!s:>12} {c_val!s:>12} {change_str:>12}")

    print("  " + "-" * 70)
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
