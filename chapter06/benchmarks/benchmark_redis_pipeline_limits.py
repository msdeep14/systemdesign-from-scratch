import argparse
import time
import threading
import redis
import concurrent.futures

def parse_args():
    parser = argparse.ArgumentParser(description="Benchmark Redis Pipelining Limits (Event Loop Blocking)")
    parser.add_argument('--redis-host', type=str, default='localhost', help='Redis server host')
    parser.add_argument('--redis-port', type=int, default=6379, help='Redis server port')
    parser.add_argument('--redis-db', type=int, default=1, help='Redis DB index')
    parser.add_argument('--pipeline-size', type=int, default=500000, help='Number of commands in the massive pipeline (simulates followers)')
    parser.add_argument('--concurrency', type=int, default=1, help='Number of concurrent workers sending massive pipelines')
    return parser.parse_args()

def monitor_latency(client, stop_event, latencies):
    """
    Continuously pings Redis every 10ms and records the latency.
    This simulates other unrelated users/workers trying to access Redis.
    """
    while not stop_event.is_set():
        start = time.time()
        try:
            client.ping()
        except Exception:
            pass
        duration = time.time() - start
        latencies.append(duration)
        time.sleep(0.01)

def build_and_execute_pipeline(worker_id, args):
    """Builds and executes a massive pipeline for a single worker."""
    client = redis.Redis(host=args.redis_host, port=args.redis_port, db=args.redis_db)
    photo_id = f"blocked_photo_{worker_id}"
    keys = [f":1:feed:dummy_celeb_{worker_id}_{i}" for i in range(args.pipeline_size)]
    
    pipeline = client.pipeline(transaction=False)
    
    # Measure memory bloat
    build_start = time.time()
    for key in keys:
        pipeline.lpush(key, photo_id)
    build_time = time.time() - build_start
    
    # Execute
    exec_start = time.time()
    try:
        pipeline.execute()
    except Exception as e:
        print(f"   Worker {worker_id} pipeline execution failed: {e}")
    exec_time = time.time() - exec_start
    
    # Cleanup
    cleanup_pipeline = client.pipeline(transaction=False)
    for i, key in enumerate(keys):
        cleanup_pipeline.delete(key)
        if i > 0 and i % 10000 == 0:
            cleanup_pipeline.execute()
    cleanup_pipeline.execute()
    
    return build_time, exec_time

def main():
    args = parse_args()
    
    print(f"Connecting to Redis at {args.redis_host}:{args.redis_port} (DB {args.redis_db})")
    
    monitor_client = redis.Redis(host=args.redis_host, port=args.redis_port, db=args.redis_db)
    
    try:
        monitor_client.ping()
    except redis.ConnectionError as e:
        print(f"Failed to connect to Redis: {e}")
        return

    print(f"\n1. Starting latency monitor to simulate other users accessing Redis...")
    stop_event = threading.Event()
    latencies = []
    monitor_thread = threading.Thread(target=monitor_latency, args=(monitor_client, stop_event, latencies))
    monitor_thread.start()
    
    # Wait a moment to gather baseline latency
    time.sleep(1)
    
    print(f"\n2. Executing {args.concurrency} massive pipelines of {args.pipeline_size} commands each concurrently...")
    print(f"   Total Redis Operations: {args.concurrency * args.pipeline_size}")
    print(f"   Watch how this blocks the Redis Event Loop for other clients!")
    
    exec_start = time.time()
    build_times = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(build_and_execute_pipeline, i, args) for i in range(args.concurrency)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
    total_exec_time = time.time() - exec_start
    avg_build_time = sum([r[0] for r in results]) / len(results)
    print(f"   All pipelines executed and cleaned up in {total_exec_time:.2f} seconds.")
    
    # Stop monitor
    stop_event.set()
    monitor_thread.join()
    
    # Analyze latencies
    baseline_latencies = latencies[:90]
    avg_baseline = (sum(baseline_latencies) / len(baseline_latencies)) * 1000 if baseline_latencies else 0
    max_latency = max(latencies) * 1000
    
    print("\n--- PIPELINE BOTTLENECK RESULTS ---")
    print(f"Concurrency: {args.concurrency} workers")
    print(f"Pipeline Size: {args.pipeline_size} commands per worker")
    print(f"Total Commands: {args.concurrency * args.pipeline_size}")
    print(f"Average Client-side Memory Build Time: {avg_build_time:.2f} seconds")
    print(f"Total Execution Time (Including Cleanup): {total_exec_time:.2f} seconds")
    print(f"Normal Redis Latency (Baseline): {avg_baseline:.2f} ms")
    print(f"Spike Redis Latency (Blocked): {max_latency:.2f} ms")
    
    print("\n--- ANALYSIS ---")
    print("While the pipeline avoids network round-trips for the worker sending it,")
    print("it forces the single-threaded Redis server to process massive buffers of commands.")
    print("During this execution window, Redis is completely BLOCKED.")
    print(f"Any other user trying to load their feed experienced up to {max_latency:.2f} ms of latency!")
    print("Furthermore, building these massive pipelines consumes significant memory across all Celery workers.")

if __name__ == "__main__":
    main()
