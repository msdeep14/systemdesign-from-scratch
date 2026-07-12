# Scaling the Database Layer

In Chapter04, we optimized individual queries (N+1 fixes, indexes, query restructuring). With traffic grows, the **single database instance itself** becomes the bottleneck.

---

## The Problem

Currently, all traffic flows through one PostgreSQL instance:

```
Nginx (LB) --> App Node 1 (gunicorn) --\
           --> App Node 2 (gunicorn) ---+--> DB instance
           --> App Node 3 (gunicorn) --/
```

Every read (newsfeed, profiles, search, notifications) and every write (photo uploads, likes, comments, follows) hits the same DB instance. As concurrent users increase:

1. **CPU/IO contention**: Reads and writes compete for the same CPU and disk I/O. Write-heavy operations slow down reads.
2. **Connection limits**: PostgreSQL default `max_connections = 100`. Each Gunicorn worker holds one connection. With 4 app nodes x 5 workers = 20 connections. Scale the ASG to 10 nodes and that's 50 connections. Add connection-per-request patterns and you hit the ceiling fast.
3. **Lock contention**: Writes acquire row-level and page-level locks. Heavy write traffic causes reads to wait.

We simulate this problem by sending concurrent HTTP traffic and measure the latency degradation.

## Vertical vs Horizontal Scaling

There are two ways to handle a database that can't keep up:

**Vertical scaling** (bigger machine): Move PostgreSQL to a larger EC2 instance — more CPU, more RAM, faster disk (io2 EBS or local NVMe). This is simple (no code changes) but has two problems:
- There is a ceiling. The largest EC2 instance (`u-24tb1.metal`, 448 vCPUs, 24TB RAM) is expensive and still just one machine.
- It doesn't solve the fundamental problem: reads and writes still compete for the same resources.

The trade-off analysis are similar to what we discussed for vertical scaling app servers.

**Horizontal scaling** (more machines): Add more database instances. But unlike stateless app servers, databases hold data. You can't just spin up another PostgreSQL and have it work. You need replication — a way to keep data in sync across instances.

There are two main approaches:

1. **Replication**: Master-slave (or leader-follower) setup where writes go to master and reads are distributed among slaves.
2. **Sharding**: Splitting data across multiple masters based on a sharding key. We'll explore this later in further chapters.

Given the fact that PhotoZ is read-heavy, read replicas are a good fit. Roughly 90% of requests are reads (browsing newsfeeds, viewing profiles, searching) and only 10% are writes (uploading photos, liking, commenting). Instead of scaling the entire database, we can scale reads independently by adding **read replicas**.

---

## Load Test: Proving the Bottleneck

### Prerequisites

1. **Running PhotoZ stack** (local Docker or EC2):
   ```bash
   cd photoz
   docker compose up -d
   ```

2. **Seeded database** (if not already done):
   ```bash
   source photoz/venv/bin/activate
   python chapter04/query_optimization/seed_data.py --reset
   ```

3. **Python dependencies** for the load test:
   ```bash
   pip install requests psycopg2-binary
   ```
psycopg2-binary helps in connecting to database directly and query pg_stat_activity to check DB connections.

### Running the Load Test

**Against local Docker (nginx on port 80):**
```bash
python chapter04/read_replicas/benchmark_db_load.py \
  --target http://localhost \
  --concurrency 30 \
  --duration 30 \
  --save-to chapter04/read_replicas/baseline.json
```

**Against EC2 load balancer:**
```bash
python chapter04/read_replicas/benchmark_db_load.py \
  --target http://<LB_PUBLIC_IP> \
  --concurrency 50 \
  --duration 60 \
  --save-to chapter04/read_replicas/baseline.json
  --db-host localhost
```

### Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--target` | (required) | Base URL of the load balancer |
| `--concurrency` | 30 | Number of concurrent simulated users |
| `--read-ratio` | 0.7 | Fraction of users doing reads (0.7 = 70% readers, 30% writers) |
| `--duration` | 30 | Test duration in seconds |
| `--save-to` | (none) | Save results to a JSON file for later comparison |
| `--compare` | (none) | Path to a baseline JSON file to compare against |
| `--db-host` | localhost | PostgreSQL host for connection stats |

### What to Look For

**At low concurrency (10 users):** Everything is fine. Reads complete in 50-100ms, writes in 30-50ms.

**At high concurrency (50+ users):** Read latency spikes to 500ms+. Write latency increases. 5xx errors start appearing as Gunicorn workers time out waiting for the database. The single PostgreSQL instance becomes saturated — CPU usage spikes, `pg_stat_activity` shows connections queuing.

The output includes:
- **Latency percentiles** (avg, p50, p95, p99) for reads and writes separately
- **Throughput** (requests per second)
- **5xx error count** (indicates server overload)
- **PostgreSQL connection count** (before and during the test)
- **Per-endpoint breakdown** (which pages are slowest)

### Saving and Comparing Results

Save the baseline (single-instance) results:
```bash
python chapter04/read_replicas/benchmark_db_load.py \
  --target http://localhost --save-to baseline.json
```

After setting up read replicas (Part 4.2+), run the same test with `--compare`:
```bash
python chapter04/read_replicas/benchmark_db_load.py \
  --target http://localhost --compare baseline.json
```

This prints a side-by-side comparison showing the improvement from read replicas.
