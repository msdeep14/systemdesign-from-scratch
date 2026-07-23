#!/usr/bin/env python3
"""
Test script to detect "Read Your Writes" consistency violations.

How This Script Works:
    1. Logs in as test_user.
    2. Finds a photo to comment on.
    3. Posts a unique comment via the JSON API (write -> primary).
    4. Immediately fetches the photo detail page (read -> possibly replica).
    5. Checks if the comment text appears in the HTML response.
    6. Repeats N times and reports the consistency rate.

Usage:
    python test_ryw_consistency.py --url http://localhost
    python test_ryw_consistency.py --url http://<lb-ip> --iterations 50
"""

import argparse
import json
import re
import sys
import time
import uuid

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

    # Wait for the session write to replicate to the replica!
    # Without this, the immediate redirect to /newsfeed will hit the replica,
    # find no session, and redirect back to login.
    time.sleep(1.5)
    
    # Manually follow the redirect
    if resp.status_code == 302:
        resp = session.get(f"{base_url}{resp.headers['Location']}")

    logged_in = resp.status_code == 200 and "/users/login/" not in resp.url
    if not logged_in:
        print(f"DEBUG: Login failed. Status={resp.status_code}, URL={resp.url}")
        print(f"DEBUG: Form errors or response text excerpt: {resp.text[:500]}")
    return logged_in


def find_photo_id(session, base_url):
    """Scrape the newsfeed to find a valid photo ID."""
    resp = session.get(f"{base_url}/", timeout=15)
    if resp.status_code != 200:
        return None

    matches = re.findall(r'/photos/(\d+)/', resp.text)
    if matches:
        return int(matches[0])
    return None


def run_test(base_url, username, password, iterations, delay_ms, show_headers=False):
    session = requests.Session()
    session.headers.update({"User-Agent": "RYW-ConsistencyTest/1.0"})

    print(f"Logging in as '{username}'...")
    if not login(session, base_url, username, password):
        print("ERROR: Login failed. Is the database seeded with test_user?")
        sys.exit(1)
    print("Login successful.")

    photo_id = find_photo_id(session, base_url)
    if not photo_id:
        print("ERROR: Could not find any photo ID on the newsfeed.")
        sys.exit(1)
    print(f"Using photo ID: {photo_id}")

    print(f"\nRunning {iterations} write-then-read tests (delay={delay_ms}ms)...\n")
    print(f"{'#':<6} {'Comment UUID':<40} {'Write':<8} {'Read':<8} {'Found':<8} {'Result'}")
    print("-" * 100)

    consistent = 0
    inconsistent = 0
    write_errors = 0

    csrf_token = session.cookies.get("csrftoken", "")
    comment_url = f"{base_url}/photos/{photo_id}/comment/"
    detail_url = f"{base_url}/photos/{photo_id}/"

    for i in range(1, iterations + 1):
        marker = f"ryw-test-{uuid.uuid4().hex[:12]}"

        # Step 1: Write a comment with a unique marker
        write_resp = session.post(
            comment_url,
            data=json.dumps({"text": marker}),
            headers={
                "X-CSRFToken": csrf_token,
                "Content-Type": "application/json",
                "Referer": detail_url,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=15,
        )

        if show_headers:
            print("\n--- WRITE REQUEST HEADERS ---")
            for k, v in write_resp.request.headers.items():
                print(f"{k}: {v}")
            print("--- WRITE RESPONSE HEADERS ---")
            for k, v in write_resp.headers.items():
                print(f"{k}: {v}")

        if write_resp.status_code != 200:
            write_errors += 1
            print(f"{i:<6} {marker:<40} {write_resp.status_code:<8} {'--':<8} {'--':<8} WRITE_ERROR")
            continue

        # Step 2: Wait the configured delay
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

        # Step 3: Read the photo detail page
        read_resp = session.get(detail_url, timeout=15)
        read_status = read_resp.status_code

        if show_headers:
            print("--- READ REQUEST HEADERS ---")
            for k, v in read_resp.request.headers.items():
                print(f"{k}: {v}")
            print("--- READ RESPONSE HEADERS ---")
            for k, v in read_resp.headers.items():
                print(f"{k}: {v}")
            print("")

        # Step 4: Check if the unique marker is in the response HTML
        found = marker in read_resp.text

        if found:
            consistent += 1
            result = "OK"
        else:
            inconsistent += 1
            result = "STALE READ"

        print(f"{i:<6} {marker:<40} {write_resp.status_code:<8} {read_status:<8} {str(found):<8} {result}")

    # Summary
    total_valid = consistent + inconsistent
    print("\n" + "=" * 100)
    print("RESULTS SUMMARY")
    print("=" * 100)
    print(f"  Total iterations:     {iterations}")
    print(f"  Write errors:         {write_errors}")
    print(f"  Consistent reads:     {consistent}")
    print(f"  Stale reads:          {inconsistent}")
    if total_valid > 0:
        rate = (consistent / total_valid) * 100
        print(f"  Consistency rate:     {rate:.1f}%")

        if inconsistent > 0:
            print(f"\n  VERDICT: Read Your Writes consistency is BROKEN.")
            print(f"           {inconsistent} out of {total_valid} reads returned stale data.")
        else:
            print(f"\n  VERDICT: Read Your Writes consistency is OK.")
            print(f"           All {total_valid} reads returned fresh data.")
    else:
        print("\n  VERDICT: No valid test results (all writes failed).")

    return inconsistent


def main():
    parser = argparse.ArgumentParser(
        description="Test Read Your Writes consistency in PhotoZ"
    )
    parser.add_argument(
        "--url",
        default="http://localhost",
        help="Base URL of the PhotoZ application (default: http://localhost)",
    )
    parser.add_argument(
        "--username",
        default="test_user",
        help="Username to log in with (default: test_user)",
    )
    parser.add_argument(
        "--password",
        default="password123",
        help="Password for the test user (default: password123)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=20,
        help="Number of write-then-read cycles (default: 20)",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=0,
        help="Milliseconds to wait between write and read (default: 0)",
    )
    parser.add_argument(
        "--show-headers",
        action="store_true",
        help="Show request and response headers in the output",
    )
    args = parser.parse_args()

    stale_count = run_test(
        args.url, args.username, args.password, args.iterations, args.delay_ms, args.show_headers
    )
    sys.exit(1 if stale_count > 0 else 0)


if __name__ == "__main__":
    main()
