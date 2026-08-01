#!/usr/bin/env python3
"""
Benchmark: CDN (CloudFront) vs Direct S3 Latency

What it measures:
    - Fetches the same photo N times via direct S3 URL and via CloudFront CDN URL.
    - Records Time to First Byte (TTFB) and total download time for each request.
    - Detects CloudFront cache HIT/MISS via the x-cache response header.
    - Prints a comparison table showing the latency reduction from CDN caching.

Usage:
    python chapter04/caching/cdn/benchmark_cdn.py \
        --s3-url "https://s3.ap-south-1.amazonaws.com/bucket/photos/42/photo_abc.jpg" \
        --cdn-url "https://d1234abcdef.cloudfront.net/photos/42/photo_abc.jpg" \
        --requests 20

How to get the URLs:
    1. Open the app in a browser, right-click any photo, "Copy Image Address".
       That gives you the CDN URL (if CDN is configured) or the S3 URL (if not).
    2. The S3 URL pattern: https://s3.<region>.amazonaws.com/<bucket>/<path>
    3. The CDN URL pattern: https://<distribution>.cloudfront.net/<path>
       Both share the same <path> portion.
"""

import argparse
import statistics
import time
import sys

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def measure_request(url):
    start = time.monotonic()
    resp = requests.get(url, stream=True, timeout=30)
    first_chunk = next(resp.iter_content(chunk_size=1024), None)
    ttfb = time.monotonic() - start

    for _ in resp.iter_content(chunk_size=8192):
        pass
    total = time.monotonic() - start

    x_cache = resp.headers.get('x-cache', 'N/A')
    content_length = int(resp.headers.get('content-length', 0))

    return {
        'status': resp.status_code,
        'ttfb_ms': round(ttfb * 1000, 2),
        'total_ms': round(total * 1000, 2),
        'x_cache': x_cache,
        'size_kb': round(content_length / 1024, 1),
    }


def run_benchmark(url, label, num_requests):
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"  URL: {url[:80]}...")
    print(f"  Requests: {num_requests}")
    print(f"{'=' * 60}")

    results = []
    for i in range(num_requests):
        try:
            result = measure_request(url)
            results.append(result)
            cache_info = f"  [{result['x_cache']}]" if result['x_cache'] != 'N/A' else ""
            print(f"  #{i+1:3d}  TTFB: {result['ttfb_ms']:8.2f}ms  "
                  f"Total: {result['total_ms']:8.2f}ms  "
                  f"Status: {result['status']}{cache_info}")
        except Exception as e:
            print(f"  #{i+1:3d}  ERROR: {e}")

    if not results:
        print("  No successful requests.")
        return None

    ttfbs = [r['ttfb_ms'] for r in results]
    totals = [r['total_ms'] for r in results]

    # For CDN, separate cold (first MISS) from warm (HIT) requests
    hit_ttfbs = [r['ttfb_ms'] for r in results if 'Hit' in r.get('x_cache', '')]
    miss_count = sum(1 for r in results if 'Miss' in r.get('x_cache', ''))
    hit_count = len(hit_ttfbs)

    summary = {
        'label': label,
        'avg_ttfb': round(statistics.mean(ttfbs), 2),
        'median_ttfb': round(statistics.median(ttfbs), 2),
        'p95_ttfb': round(sorted(ttfbs)[int(len(ttfbs) * 0.95)], 2) if len(ttfbs) >= 2 else ttfbs[0],
        'avg_total': round(statistics.mean(totals), 2),
        'size_kb': results[0]['size_kb'],
        'hit_count': hit_count,
        'miss_count': miss_count,
        'warm_avg_ttfb': round(statistics.mean(hit_ttfbs), 2) if hit_ttfbs else None,
    }

    return summary


def print_comparison(s3_summary, cdn_summary):
    print(f"\n{'=' * 60}")
    print(f"  COMPARISON: S3 Direct vs CloudFront CDN")
    print(f"{'=' * 60}")

    print(f"\n  {'Metric':<30} {'S3 Direct':>12} {'CloudFront':>12} {'Reduction':>12}")
    print(f"  {'-' * 66}")

    s3_ttfb = s3_summary['avg_ttfb']
    cdn_ttfb = cdn_summary['avg_ttfb']
    reduction = round(((s3_ttfb - cdn_ttfb) / s3_ttfb) * 100, 1) if s3_ttfb > 0 else 0

    print(f"  {'Avg TTFB (ms)':<30} {s3_ttfb:>12.2f} {cdn_ttfb:>12.2f} {reduction:>11.1f}%")

    s3_med = s3_summary['median_ttfb']
    cdn_med = cdn_summary['median_ttfb']
    med_reduction = round(((s3_med - cdn_med) / s3_med) * 100, 1) if s3_med > 0 else 0
    print(f"  {'Median TTFB (ms)':<30} {s3_med:>12.2f} {cdn_med:>12.2f} {med_reduction:>11.1f}%")

    s3_p95 = s3_summary['p95_ttfb']
    cdn_p95 = cdn_summary['p95_ttfb']
    p95_reduction = round(((s3_p95 - cdn_p95) / s3_p95) * 100, 1) if s3_p95 > 0 else 0
    print(f"  {'P95 TTFB (ms)':<30} {s3_p95:>12.2f} {cdn_p95:>12.2f} {p95_reduction:>11.1f}%")

    s3_total = s3_summary['avg_total']
    cdn_total = cdn_summary['avg_total']
    total_reduction = round(((s3_total - cdn_total) / s3_total) * 100, 1) if s3_total > 0 else 0
    print(f"  {'Avg Total Time (ms)':<30} {s3_total:>12.2f} {cdn_total:>12.2f} {total_reduction:>11.1f}%")

    print(f"  {'Image Size (KB)':<30} {s3_summary['size_kb']:>12.1f} {cdn_summary['size_kb']:>12.1f}")

    if cdn_summary['hit_count'] + cdn_summary['miss_count'] > 0:
        total_cdn = cdn_summary['hit_count'] + cdn_summary['miss_count']
        hit_ratio = round((cdn_summary['hit_count'] / total_cdn) * 100, 1)
        print(f"\n  CloudFront Cache:")
        print(f"    HITs: {cdn_summary['hit_count']}, MISSes: {cdn_summary['miss_count']}, HIT Ratio: {hit_ratio}%")

        if cdn_summary['warm_avg_ttfb'] is not None:
            warm_reduction = round(((s3_ttfb - cdn_summary['warm_avg_ttfb']) / s3_ttfb) * 100, 1) if s3_ttfb > 0 else 0
            print(f"    Avg TTFB (cache HITs only): {cdn_summary['warm_avg_ttfb']:.2f}ms ({warm_reduction}% faster than S3)")


def main():
    parser = argparse.ArgumentParser(description='Benchmark CDN vs Direct S3 latency')
    parser.add_argument('--s3-url', required=True, help='Direct S3 URL of a photo')
    parser.add_argument('--cdn-url', required=True, help='CloudFront CDN URL of the same photo')
    parser.add_argument('--requests', type=int, default=20, help='Number of requests per URL (default: 20)')
    args = parser.parse_args()

    print(f"\nCDN Benchmark: {args.requests} requests to each URL")
    print(f"Run from: your current machine location")
    print(f"For best results, also run this from an EC2 in a different region.\n")

    s3_summary = run_benchmark(args.s3_url, "Direct S3", args.requests)
    cdn_summary = run_benchmark(args.cdn_url, "CloudFront CDN", args.requests)

    if s3_summary and cdn_summary:
        print_comparison(s3_summary, cdn_summary)
    else:
        print("\nBenchmark incomplete - one or both URLs failed.")
        sys.exit(1)


if __name__ == '__main__':
    main()
