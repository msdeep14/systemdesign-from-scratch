#!/usr/bin/env python3
"""
HTTP benchmark for likes/comments count queries -- tests against AWS deployment.

Unlike benchmark_before.py (which talks directly to the DB), this script fires
real HTTP requests to the deployed application, measuring end-to-end latency
as a real user would experience it: through Nginx, Gunicorn, Django middleware,
Redis cache, and the actual Postgres queries.

Three page scenarios are benchmarked:
    1. Newsfeed  -- fires 2 extra COUNT GROUP BY queries per load (before denormalization)
    2. Profile   -- fires 2 COUNT queries per photo (N+1 pattern)
    3. Photo detail -- fires 1 COUNT query for likes

Run BEFORE the denormalization migration to establish baseline.
Run benchmark_after_http.py after Stage 2 deploy to compare.

Usage:
    python chapter04/denormalization/benchmark_before_http.py \\
        --url http://<lb-public-ip> \\
        --username <test_user> \\
        --password <password> \\
        --iterations 20

Optional:
    --concurrency 5    Run N concurrent requests per scenario (default: 1 = sequential)
    --photo-id 1234    Specific photo ID to use for photo_detail benchmark
"""

import argparse
import concurrent.futures
import re
import statistics
import sys
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def login(base_url, username, password):
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "Photoz-Denorm-Benchmark/1.0"})

    login_url = f"{base_url}/users/login/"
    resp = session.get(login_url, timeout=15)
    if resp.status_code != 200:
        print(
            f"ERROR: Could not reach login page (status {resp.status_code}): {login_url}"
        )
        sys.exit(1)

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
        allow_redirects=True,
    )

    logged_in = resp.status_code == 200 and "/users/login/" not in resp.url
    if not logged_in:
        print(f"ERROR: Login failed. Status={resp.status_code}, URL={resp.url}")
        sys.exit(1)

    print(f"  Logged in as: {username}")
    print(f"  Landed on:    {resp.url}")
    # Return session and the post-login landing page (this is the feed URL)
    return session, resp.url, resp.text


def get_profile_url(base_url, html, username):
    """
    Extract the full profile URL from the page HTML.
    Looks for any href containing /profile/ or /users/ with a username path.
    Falls back to constructing from the username if no link found.
    """
    # Try to find a profile link in the nav or page (e.g. "My Profile" link)
    for pattern in [
        r'href="(/[^"]*profile[^"]*/' + re.escape(username) + r'[^"]*?)"',
        r"href='(/[^']*profile[^']*/')",
        r'href="(/users/[^"]+/?)"',
    ]:
        match = re.search(pattern, html)
        if match:
            path = match.group(1).rstrip("/")
            return f"{base_url}{path}/"
    return None


def get_sample_photo_id(html, debug=False):
    """Extract a photo ID from page HTML to use for photo_detail benchmark."""
    for pattern in [r"/photos/(\d+)/", r"photo/(\d+)/", r"detail/(\d+)/"]:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    if debug:
        print("\n  DEBUG: Could not find photo ID. First 3000 chars of page:")
        print("  " + "-" * 60)
        print(html[:3000])
        print("  " + "-" * 60)
    return None


def make_thread_session(auth_session):
    """
    Create a new requests.Session for use in a worker thread.

    requests.Session is not thread-safe -- sharing one session across threads
    corrupts cookie state under concurrent load, causing random auth failures.
    This creates an independent session per thread that copies the cookies and
    headers from the authenticated session.
    """
    s = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.cookies.update(auth_session.cookies)
    s.headers.update(auth_session.headers)
    return s


def fetch_url(auth_session, url):
    session = make_thread_session(auth_session)
    start = time.perf_counter()
    try:
        resp = session.get(url, timeout=30)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return resp.status_code, elapsed_ms
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return str(e), elapsed_ms


def run_scenario(session, url, label, iterations, concurrency):
    """
    Run a single URL scenario for a given number of iterations.
    Returns latency stats (ms).
    """
    print(f"\n  {label}")
    print(f"  URL: {url}")
    print(f"  Iterations: {iterations}, Concurrency: {concurrency}")
    print("  " + "-" * 60)

    latencies = []
    errors = 0
    error_samples = []  # Collect a few failure details to aid debugging

    if concurrency == 1:
        for i in range(iterations):
            status, ms = fetch_url(session, url)
            if isinstance(status, int) and 200 <= status < 400:
                latencies.append(ms)
            else:
                errors += 1
                if len(error_samples) < 3:
                    error_samples.append(status)
            if (i + 1) % 5 == 0:
                print(f"    [{i + 1}/{iterations}] last: {ms:.0f}ms")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(fetch_url, session, url) for _ in range(iterations)
            ]
            for i, f in enumerate(concurrent.futures.as_completed(futures)):
                status, ms = f.result()
                if isinstance(status, int) and 200 <= status < 400:
                    latencies.append(ms)
                else:
                    errors += 1
                    if len(error_samples) < 3:
                        error_samples.append(status)

    if not latencies:
        print(f"  ERROR: All {iterations} requests failed.")
        if error_samples:
            print(f"  Sample failure statuses/errors: {error_samples}")
            if any(s == 302 or s == 301 for s in error_samples if isinstance(s, int)):
                print(
                    "  Hint: Redirects to login -- session auth is not carrying across requests."
                )
            elif any(s == 403 for s in error_samples if isinstance(s, int)):
                print("  Hint: 403 Forbidden -- CSRF or permissions issue.")
        return None

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    p99 = (
        sorted(latencies)[int(len(latencies) * 0.99)]
        if len(latencies) >= 100
        else max(latencies)
    )
    avg = statistics.mean(latencies)
    mn = min(latencies)
    mx = max(latencies)

    print(f"\n  Results ({len(latencies)} successful, {errors} errors):")
    print(f"    Min:  {mn:.0f}ms")
    print(f"    Avg:  {avg:.0f}ms")
    print(f"    p50:  {p50:.0f}ms")
    print(f"    p95:  {p95:.0f}ms")
    print(f"    p99:  {p99:.0f}ms")
    print(f"    Max:  {mx:.0f}ms")

    return {
        "label": label,
        "url": url,
        "min": mn,
        "avg": avg,
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "max": mx,
        "errors": errors,
        "count": len(latencies),
    }


def print_summary(results):
    print("\n\n" + "=" * 70)
    print("  BEFORE DENORMALIZATION -- HTTP Latency Baseline (AWS)")
    print("  Run benchmark_after_http.py after Stage 2 deploy to compare.")
    print("=" * 70)
    print(f"  {'Scenario':<30} {'Avg':>7} {'p50':>7} {'p95':>7} {'p99':>7} {'Max':>7}")
    print("  " + "-" * 66)
    for r in results:
        if r:
            print(
                f"  {r['label']:<30} {r['avg']:>6.0f}ms {r['p50']:>6.0f}ms "
                f"{r['p95']:>6.0f}ms {r['p99']:>6.0f}ms {r['max']:>6.0f}ms"
            )
    print("  " + "-" * 66)
    print()
    print("  Note: These numbers include HTTP overhead, Nginx, Gunicorn, Redis,")
    print("  and network latency -- the full user experience, not just DB time.")
    print()
    print("  After denormalization, COUNT(*) queries are eliminated from the hot")
    print("  path. The reduction in p50/p95 latency shows the real-world gain.")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="HTTP benchmark for Photoz likes/comments count (before denormalization)"
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Base URL of the deployed app (e.g. http://1.2.3.4)",
    )
    parser.add_argument("--username", required=True, help="Login username")
    parser.add_argument("--password", required=True, help="Login password")
    parser.add_argument(
        "--iterations", type=int, default=20, help="Requests per scenario (default: 20)"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Concurrent requests per scenario (default: 1)",
    )
    parser.add_argument(
        "--photo-id",
        type=str,
        default=None,
        help="Photo ID to use for photo_detail benchmark",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print HTML snippet when photo ID detection fails",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  Photoz -- Denormalization HTTP Benchmark (BEFORE)")
    print("  Tests against live AWS deployment")
    print("=" * 70)
    print(f"\n  Target: {args.url}")
    print(f"  Iterations per scenario: {args.iterations}")
    print(f"  Concurrency: {args.concurrency}")

    session, feed_url, feed_html = login(args.url, args.username, args.password)

    profile_url = (
        args.photo_id and None or get_profile_url(args.url, feed_html, args.username)
    )
    if not profile_url:
        # Try fetching the feed page explicitly in case it differs from the landing page
        resp = session.get(feed_url, timeout=15)
        profile_url = get_profile_url(args.url, resp.text, args.username)
    print(f"  Profile URL:  {profile_url or 'not found -- will skip'}")

    photo_id = args.photo_id or get_sample_photo_id(feed_html, debug=args.debug)
    if not photo_id:
        print(
            "  WARNING: Could not find a photo ID from the newsfeed. Photo detail benchmark skipped."
        )
        print(
            "  Tip: Re-run with --debug to inspect the feed HTML, or pass --photo-id <id> directly."
        )
    else:
        print(f"  Sample photo ID: {photo_id}")

    results = []

    print("\n" + "=" * 70)
    print("  BENCHMARK 1: Newsfeed Page Load")
    print(
        "  (2 COUNT GROUP BY queries per load -- likes + comments for page of photos)"
    )
    print("=" * 70)
    results.append(
        run_scenario(
            session,
            feed_url,
            "Newsfeed",
            args.iterations,
            args.concurrency,
        )
    )

    if profile_url:
        print("\n" + "=" * 70)
        print("  BENCHMARK 2: Profile Page")
        print("  (photo.likes.count() + photo.comments.count() per photo -- N+1 COUNT)")
        print("=" * 70)
        results.append(
            run_scenario(
                session,
                profile_url,
                "Profile page",
                args.iterations,
                args.concurrency,
            )
        )

    if photo_id:
        print("\n" + "=" * 70)
        print("  BENCHMARK 3: Photo Detail Page")
        print("  (single photo.likes.count() call)")
        print("=" * 70)
        results.append(
            run_scenario(
                session,
                f"{args.url}/photos/{photo_id}/",
                "Photo detail",
                args.iterations,
                args.concurrency,
            )
        )

    print_summary(results)


if __name__ == "__main__":
    main()
