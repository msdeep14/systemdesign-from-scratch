# Multi-Tier Cache Abstraction & Workload Isolation

This document outlines the multi-tier caching abstraction and deployment routing architecture in Photoz.

---

## 1. Motivation & Architecture

Photoz handles divergent caching workloads:
* **High-Churn, Large Data (Newsfeeds):** Unbounded lists of photo IDs updated via fan-out writes (`RPUSH`, `LRANGE`, `LTRIM`).
* **Critical Counters & Locks (Likes, Feeds Locks):** Atomic integers (`INCRBY`) and mutex locks (`SET nx=True, ex=5`) that must not be evicted.
* **Read-Heavy Shared Metadata (Celebrity Photos):** Identical photo lists queried by thousands of followers simultaneously during read-time feed generation.

### The Solution: Multi-Tier Cache Abstraction

The unified abstraction in [`photoz/bses/cache.py`](../../photoz/bses/cache.py) introduces two primary concepts:

```
Request 
   │
   ▼
1. Check Local L1 (`tier="local"`, LocMemCache) ────[Hit]──> Return (< 0.01 ms)
   │ [Miss]
   ▼
2. Check Redis L2 (`tier="core"`, Shared Cluster) ──[Hit]──> Backfill L1 & Return (~0.5 ms)
   │ [Miss]
   ▼
3. Thundering Herd Protection (stampede_protection=True)
   ├── [Lock Winner]  ──> Query PostgreSQL ──> Backfill L2 & L1 ──> Release Lock
   └── [Lock Waiters] ──> Poll Redis (Cache Promise) for up to 1.0s ──> Return Result
```

1. **Tiered Key-Value Operations:** Standardizes `get`, `set`, and `get_or_set` across in-process local memory (`LocMemCache`) and remote Redis instances without hardcoding connection strings.
2. **Deployment-Aware Client Registry:** Direct access to raw Redis clients (`get_client(deployment, for_write)`) with automated read/write splitting between primary and read replicas.

---

## 2. In-Process (LocMemCache) vs. Pod/Instance-Level Caching Analysis

### The Scoping Question: Process vs. Pod vs. Instance
In Python web applications, Gunicorn runs multiple worker processes (pre-fork model) to handle concurrency because of the Global Interpreter Lock (GIL).
- **Process-Level (`LocMemCache`):** Data is stored in a Python dictionary in that single worker's virtual memory address space. Worker A cannot read Worker B's memory.
- **Pod / Instance-Level:** Requires inter-process communication (IPC) such as POSIX shared memory (`/dev/shm`), memory-mapped files (`mmap`), or a local container daemon (Redis or Memcached sidecar).

### Caffeine Comparison (Why Java Differs from Python)
- In the Java ecosystem, **Caffeine** uses Window TinyLFU (W-TinyLFU) to track recency and frequency, delivering near-optimal cache hit ratios. Because all request threads run inside a single JVM process, they share one heap. One Caffeine instance automatically serves the entire pod without duplicating memory.
- In Python, running multiple worker processes means any in-process memory cache is replicated inside each worker process.

### Memory Overhead & Sizing Math
Is memory duplication across Python workers an operational problem?
- `LocMemCache` is explicitly capped at `MAX_ENTRIES = 1000` with a 5-second TTL.
- A list of 20 integer photo IDs takes roughly 200 bytes.
- 1,000 cached entries consume approximately 1 to 2 MB of RAM per worker process.
- On an EC2 instance with 4 Gunicorn workers, total memory consumption across all workers is **~6 MB**.
- On a 1 GB or 2 GB server, 6 MB is less than 0.5% of total system memory.

### Trade-Off Comparison

| Strategy | Architecture | Latency | Complexity | When to Use |
| :--- | :--- | :--- | :--- | :--- |
| **Process-Level (`LocMemCache`)** | Isolated Python dict per worker process | **< 0.01 ms** | **Low.** Zero external dependencies or daemons. | Small, transient metadata (celebrity IDs, user flags). |
| **Threaded Workers (`gthread`)** | 1 worker process with multiple threads | **< 0.01 ms** | **Low.** Zero duplication; all threads share single `LocMemCache`. | When workload is I/O-bound and worker memory must be consolidated. |
| **Shared Memory IPC (`/dev/shm`)** | Python processes share an mmap buffer | **~0.05 ms** | **High.** Requires binary serialization, fixed buffer sizes, and cross-process locks. | Massive datasets where network hops are unacceptable. |
| **Node-Local Sidecar (Local Redis)** | Container daemon on `localhost` | **~0.2 ms** | **Medium.** Single copy of data, but requires socket serialization and extra container operations. | Large cached objects (> 100 MB) across dozens of processes. |

### Architectural Decision
We retain `LocMemCache` (process-level) because the 6 MB memory footprint does not justify the operational and locking complexity of shared memory IPC or extra sidecar daemons. If worker memory consolidation is ever required, switching Gunicorn to the `gthread` worker engine (`--workers 1 --threads 4`) natively shares `LocMemCache` across all request threads without code modifications.

---

## 3. Configuration & Logical Deployments

Deployments are defined in [`photoz/bses/settings.py`](../../photoz/bses/settings.py):

```python
CACHES["local"] = {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "photoz-in-process-cache",
    "TIMEOUT": 5,
    "OPTIONS": {
        "MAX_ENTRIES": 1000,
    },
}

REDIS_DEPLOYMENTS = {
    "core": {
        "SENTINELS": REDIS_SENTINELS,
        "MASTER_NAME": "mymaster",
        "URL": REDIS_URL,
        "SOCKET_TIMEOUT": 0.5,
        "CONNECT_TIMEOUT": 0.5,
    },
    "feeds": {
        "URL": os.environ.get("REDIS_FEEDS_URL", "redis://localhost:6379/2"),
        "SOCKET_TIMEOUT": 1.0,
        "CONNECT_TIMEOUT": 0.5,
    },
}
```

---

## 4. How to Use `CacheService`

### A. Key-Value Caching (`get`, `set`, `get_or_set`)

```python
from bses.cache import cache_service

# 1. Store in local container memory (L1, 5-second TTL)
cache_service.set("celeb:101", photo_ids, timeout=5, tier="local")
cached = cache_service.get("celeb:101", tier="local")

# 2. Two-tier lookup with thundering herd lock protection
data = cache_service.get_or_set(
    key="celebrity_photos:500k",
    default_fn=lambda: fetch_photos_from_postgres(),
    local_timeout=5,
    redis_timeout=60,
    tier="core",
    stampede_protection=True,
)
```

### B. Redis Data Structures (`get_client`)

For operations requiring Redis lists, sets, or atomic increments:

```python
from bses.cache import cache_service

# 1. High-churn timeline lists (Feeds deployment)
feeds_master = cache_service.get_client("feeds", for_write=True)
feeds_master.rpush(f":1:feed:{user_id}", *photo_ids)

# 2. Live counters & mutex locks (Core deployment master)
core_master = cache_service.get_client("core", for_write=True)
core_master.incr(f"photo:{photo_id}:likes_count")

# 3. Read replicas for metadata & counters (Core deployment replica)
core_replica = cache_service.get_client("core", for_write=False)
likes = core_replica.get(f"photo:{photo_id}:likes_count")
```

---

## 5. Local Testing & Verification

### Running Unit Tests
From repository root (virtual environment activated):
```bash
source ./photoz/venv/bin/activate && cd photoz
python manage.py test tests.test_cache_service tests.test_celebrity_cache tests.test_feeds_redis_routing tests.test_redis_routing tests.test_likes_scalability
```

### Running Quality Checks
```bash
source ./photoz/venv/bin/activate && cd photoz
ruff check .
ruff format --check .
pylint bses/cache.py bses/redis_client.py photos/services.py newsfeed/services.py users/services.py tests/test_redis_routing.py
lint-imports
pre-commit run --all-files
```

### Container Setup
For Task 3 and Task 5, a dedicated Redis Feeds cluster handles newsfeed list operations (`RPUSH`, `LPUSH`, `LRANGE`, `LTRIM`), monitored by Redis Sentinels for High Availability:
- `redis-feeds-primary`: Primary Redis instance on port 6383 (`redis://redis-feeds-primary:6379/0`).
- `redis-feeds-replica`: Read replica on port 6384 replicating from `redis-feeds-primary`.
- `redis-sentinel` (sentinel-1, sentinel-2, sentinel-3): Monitor `feeds-master` with quorum 2.

Start the feeds cluster:
```bash
cd photoz
docker compose up -d redis-feeds-primary redis-feeds-replica
docker compose restart sentinel-1 sentinel-2 sentinel-3 web
```

### AWS Production Deployment (Terraform)
The infrastructure in `iaac/aws/terraform/` deploys workload-isolated Redis clusters and a dedicated Sentinel quorum:
- `aws_instance.redis_node` & `aws_instance.redis_replica`: Core primary and read replicas running only `redis-server`.
- `aws_instance.redis_feeds_node` & `aws_instance.redis_feeds_replica`: Feeds primary and read replica running only `redis-server`.
- `aws_instance.redis_sentinel_node`: Dedicated 3-node Sentinel cluster running on Amazon Linux 2023 Minimal (`t3.nano` by default, configured via `redis_sentinel_instance_type`). The lightweight base image uses ~80 MB RAM with 512 MB swap configured in user-data to prevent OOM errors.
- The dedicated Sentinels monitor both `mymaster` (Core cluster) and `feeds-master` (Feeds cluster) simultaneously, eliminating failure coupling between cache clusters.
- Application nodes (`app_node`) receive `REDIS_SENTINELS`, `REDIS_MASTER_NAME`, and `REDIS_FEEDS_MASTER_NAME` for dynamic topology discovery.


