# Scaling Databases with Read Replicas

Introducing a Primary-Replica database architecture.

## 1. The Bottleneck (Baseline Analysis)

For PhotoZ, the vast majority of database traffic is **read queries** (users viewing their newsfeed, checking profiles, searching for hashtags). The general read/write ratio is 90/10.

To simulate this bottleneck, we configured our single PostgreSQL instance with:
- `max_connections=20` (limiting concurrent connections)
- Docker CPU limit of `0.5` cores (simulating compute constraints). This will be updated back to original value after testing.

Ran a load test with 50 concurrent simulated users with 90% reads and 10% writes.

### Baseline Benchmark Results

The single database instance was quickly overwhelmed. 

* **Average Read Latency:** 2.2 seconds
* **p95 Read Latency:** 5.2 seconds
* **Average Write Latency:** 954 milliseconds

**Why did this happen?**
We hit a dual bottleneck: CPU and Connections.

1. **CPU Limit (50%)**: Docker Stats showed the database sitting at exactly 49.92% CPU, meaning it maxed out its `cpus: '0.5'` allocation. Because the CPU was saturated processing the flood of read queries, queries took significantly longer to execute.
2. **Connection Starvation**: As queries slowed down, PgBouncer's connection pool backed up. Postgres was configured with `max_connections=20`. However, 3 connections are reserved for superusers by default, leaving only 17 slots for our application. PgBouncer is configured to open a `default_pool_size` of 18. This caused PgBouncer to exceed Postgres's limit, leading to `FATAL: sorry, too many clients already` errors in the database logs.

```bash
CONTAINER ID   NAME                 CPU %     MEM USAGE / LIMIT     MEM %     NET I/O           BLOCK I/O         PIDS
1d5b3f2a4fc0   photoz-pgbouncer-1   1.24%     2.523MiB / 908.6MiB   0.28%     33.4MB / 33.9MB   279kB / 0B        1
6ff177b22ce5   photoz-db-1          49.92%    177.9MiB / 908.6MiB   19.58%    7.42MB / 24.6MB   31.6MB / 11.4MB   26
```

This cascading failure caused the App Servers (Gunicorn) to run out of threads waiting for PgBouncer, leading to 380 `5xx` HTTP timeouts on the load balancer.

## 2. Why Read Replicas Solve the Problem

Since majority traffic is reads, we'll introduce read replicas in the architecture.

## 3. Implementation Plan

Our implementation involves three main phases:
1. **Replication from Scratch**: Setting up PostgreSQL Streaming Replication (Asynchronous) using `pg_basebackup` and custom initialization scripts.
2. **Django Database Routing**: Implementing a custom `PrimaryReplicaRouter` in Django to automatically direct `SELECT` queries to the replica and `INSERT/UPDATE/DELETE` queries to the primary.
3. **Handling "Read Your Own Writes"**: Ensuring users don't experience replication lag immediately after posting a comment.

Refer to AWS_DEPLOYMENT.md for the AWS implementation and deployment.
For local deployment:

```bash
docker compose down -v
docker compose up -d --build
```
