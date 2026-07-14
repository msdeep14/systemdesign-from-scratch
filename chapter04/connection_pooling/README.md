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
python chapter04/connection_pooling/benchmark_db_load.py \
  --target http://localhost \
  --concurrency 30 \
  --duration 30 \
  --save-to chapter04/connection_pooling/baseline.json
```

**Against EC2 load balancer:**
Because the AWS security group restricts PostgreSQL (port 5432) access to internal app nodes only, you must first create an SSH tunnel to your DB instance to view the connection metrics:

```bash
# Keep this running in a separate terminal
ssh -i /path/to/your/aws-key.pem -L 5432:127.0.0.1:5432 ubuntu@<DB_PUBLIC_IP>
```

Then, run the benchmark (using `localhost` for the database to route through your tunnel):
```bash
python chapter04/connection_pooling/benchmark_db_load.py \
  --target http://<LB_PUBLIC_IP> \
  --concurrency 200 \
  --duration 30 \
  --save-to chapter04/connection_pooling/baseline-remote.json \
  --db-host localhost \
  --read-ratio 0.9
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
python chapter04/connection_pooling/benchmark_db_load.py \
  --target http://localhost --save-to baseline.json
```

After setting up read replicas (Part 4.2+), run the same test with `--compare`:
```bash
python chapter04/connection_pooling/benchmark_db_load.py \
  --target http://localhost --compare baseline.json
```

This prints a side-by-side comparison showing the improvement from read replicas.

## Migrating PgBouncer to SCRAM Auth (Live Database)

If you are migrating PgBouncer to use the dynamic `auth_query` pattern (Zero Trust SCRAM) on an already running AWS production database, you cannot rely on Docker's `postgres-init` directory because initialization scripts only run on fresh, empty databases. 

To apply the secure authentication without data loss or downtime:

1. **SSH into your Database Node and pull the latest code:**
   ```bash
   cd /home/ubuntu/systemdesign-from-scratch/photoz
   git pull origin main
   ```

2. **Inject the Auth Query Function into the Live Database:**
   Pipe the initialization SQL directly into the running Postgres container:
   ```bash
   cat postgres-init/01-pgbouncer-auth.sql | docker exec -i photoz-db-1 psql -U postgres -d bses
   ```

3. **Restart PgBouncer to Apply Configs:**
   Restart only the `pgbouncer` container to mount the new `pgbouncer.ini` and `userlist.txt` files, leaving the Postgres container untouched:
   ```bash
   docker compose -f docker-compose-db.yml up -d --force-recreate pgbouncer
   ```

4. **Update App Nodes to fix Django Migrations:**
   You must pull the latest code on your App Nodes to ensure the `POSTGRES_PORT=5432` override is applied to the migration command in `docker-compose-app.yml`. Otherwise, future migrations will hang in PgBouncer's transaction pool.
   ```bash
   # SSH into each App Node
   cd /home/ubuntu/systemdesign-from-scratch/photoz
   git pull origin main
   docker compose -f docker-compose-app.yml up -d --force-recreate web
   ```

For local testing, you can simply scrape off the database, then start fresh. 
```bash
# -v ensures volumes are wiped out, meaning database is wiped out
# because of -v, init script will run
docker compose down -v
docker compose up -d
```

## Important Note: Django Migrations with PgBouncer

When using PgBouncer in **transaction pooling mode** (`pool_mode = transaction`), Django migrations will often hang or fail. This is because Django (4.0+) uses PostgreSQL session-level advisory locks during migrations to prevent concurrent migration execution. In transaction mode, PgBouncer immediately returns the connection to the pool after the advisory lock transaction commits, causing subsequent migration steps to potentially receive a different connection that does not hold the lock.

To fix this, **migrations must always be run directly against the database (port 5432)**, bypassing PgBouncer (port 6432).

This is why the application node's startup command explicitly overrides the `POSTGRES_PORT` just for the `migrate` command:

```yaml
# In docker-compose.yml and docker-compose-app.yml
command: >
  bash -c "POSTGRES_HOST=db POSTGRES_PORT=5432 python manage.py migrate && python manage.py collectstatic --noinput && gunicorn ..."
```
