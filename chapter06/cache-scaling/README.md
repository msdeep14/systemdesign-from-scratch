# Redis Sentinel High Availability & Cache Scaling

This document details the architectural motivation, topology, local verification, and AWS production deployment of the Redis Sentinel High Availability cluster and user-centric like scalability optimizations implemented in Chapter 6.

---

## 1. Architectural Motivation

In social platforms with high-fanout and celebrity accounts, a standalone Redis cache suffers from three critical bottlenecks:

1. **Unbounded Memory Explosion on Hot Objects**:
   - The initial design tracked photo likes using a per-photo set (`photo:{photo_id}:likers`). For celebrity photos with millions of likes, this set grew to tens of megabytes, causing massive memory allocation and latency spikes during `SISMEMBER` checks.
   - It also caused database connection exhaustion because cache misses forced bulk-loading all likers from PostgreSQL into Redis at once.
2. **Single Point of Failure (SPOF)**:
   - A single Redis node represents a single point of failure. If the node crashes or runs out of memory, newsfeed generation, like counters, rate limiting, and distributed locks fail simultaneously.
3. **Read/Write Asymmetry & Resource Contention**:
   - Read queries (newsfeed timeline retrieval, like status checks) outnumber write operations (liking a photo, updating counters) by orders of magnitude. Forcing both read and write traffic through a single-threaded Redis process causes head-of-line blocking on heavy operations.

---

## 2. Architecture & Topology

To eliminate these bottlenecks, the caching tier is decomposed into a **Master-Replica Replication topology monitored by a distributed Redis Sentinel consensus cluster**:

```text
                     +-----------------------------------+
                     |       Django Application Fleet    |
                     +-----------------+-----------------+
                                       |
                   1. Master Discovery | (Port 26379)
                                       v
                     +-----------------------------------+
                     |      Redis Sentinel Cluster       |
                     |  (3 Nodes, Quorum 2 across AZs)   |
                     +-----------------+-----------------+
                                       |
                   2. Heartbeat & Auto | Failover
                                       v
         +-------------------------------------------------------+
         |                                                       |
         v (Writes / Port 6379)                                  v (Reads / Port 6379)
+-------------------+        Replication (TCP)          +-------------------+
|   Redis Primary   | --------------------------------> |  Redis Replicas   |
|   (Master Node)   |                                   |  (1 to N Nodes)   |
+-------------------+                                   +-------------------+
```

### Key Architectural Characteristics
- **Dedicated Read/Write Splitting**: Writes (counters, like toggles, locks) route strictly to the Primary. Reads (feed lists, like checks) route across Replicas.
- **Asymmetric Connection Pools**:
  - **Replica Pool**: Up to 50 connections to absorb high concurrent read throughput.
  - **Master Pool**: Capped at 20 connections to protect the primary from connection exhaustion.
  - **Timeouts**: 500ms socket timeouts, 500ms connect timeouts, and 30-second TCP keepalive health checks.
- **Consensus & Quorum**: Exactly 3 Sentinels maintain an odd-numbered quorum of 2. If the primary misses pings for 3,000ms (`down-after-milliseconds`), Sentinels agree via gossip protocol, elect a leader, and promote a replica to primary.

---

## 3. Likes Scalability (User-Centric Caching)

Instead of maintaining an unbounded set of users who liked a photo, we inverted the relationship:

- **Key Pattern**: `user:{user_id}:liked_photos` (Redis Set).
- **Bounded Capacity**: Tracks up to 500 recent likes per user.
- **Lookup Time**: `SISMEMBER user:{user_id}:liked_photos {photo_id}` runs in $O(1)$ time.
- **Atomic Counter**: `photo:{photo_id}:likes_count` maintains the exact like count via `INCR` / `DECR`.
- **Database Shielding**: When a user's set is cold, only that specific user's recent likes are loaded from PostgreSQL (bounded query), protecting PgBouncer and Postgres from hot-row query storms.

---

## 4. Local Development & Verification (Docker Compose)

The local environment consists of 7 containers:
- `redis-primary` (Master on port 6379)
- `redis-replica-1`, `redis-replica-2`, `redis-replica-3` (Replicas on port 6379)
- `sentinel-1`, `sentinel-2`, `sentinel-3` (Sentinels on port 26379, quorum 2)

### Step 1: Start the Cluster
```bash
cd photoz

# Remove standalone Redis container if existing
docker rm -f photoz-redis-1 2>/dev/null || true

# Start application and Sentinel cluster
docker compose up -d --remove-orphans
```

### Step 2: Verify Sentinel Cluster & Quorum Status
```bash
# Verify quorum can be reached (should return: OK 3 usable Sentinels. Quorum calculated is 2)
docker exec photoz-sentinel-1 redis-cli -p 26379 sentinel ckquorum mymaster

# Inspect current master state and replica counts
docker exec photoz-sentinel-1 redis-cli -p 26379 sentinel master mymaster

# List all connected read replicas
docker exec photoz-sentinel-1 redis-cli -p 26379 sentinel replicas mymaster

# List all peer Sentinels
docker exec photoz-sentinel-1 redis-cli -p 26379 sentinel sentinels mymaster
```

### Step 3: Test Dynamic Scale-Out (Add 4th Read Replica)
New read replicas can be added dynamically with zero downtime. Sentinel auto-discovers newly joined replicas:
```bash
# Spin up 4th replica pointing to current primary
docker run -d --name photoz-redis-replica-4 --network photoz_default redis:7 redis-server --replicaof redis-primary 6379 --protected-mode no

# Confirm Sentinel auto-discovered the 4th replica
docker exec photoz-sentinel-1 redis-cli -p 26379 sentinel master mymaster | grep -A 1 "num-slaves"
```

### Step 4: Run Automated Failover Test
Run the end-to-end failover test script:
```bash
./photoz/scripts/test_sentinel_failover.sh
```
This script pauses the primary, verifies that Sentinels detect failure and promote a replica to new primary within 5 seconds, unpauses the old primary, and verifies it re-attaches as a replica.

---

## 5. AWS Production Deployment (Terraform)

In AWS production, Redis nodes and Sentinels are distributed across Availability Zones:

- **Redis Primary**: Subnet 1 (AZ 1) running `redis-server` (6379) and Sentinel 1 (26379).
- **Redis Replicas**: Distributed across Subnets 2 and 3 (AZ 2 and AZ 3) running `redis-server` (6379).
- **Sentinel Quorum Anchor**: The first 2 replicas also run Sentinel on port 26379. This guarantees exactly 3 Sentinels across 3 distinct AZs regardless of how many read replicas are added, avoiding split-brain while keeping resource overhead minimal.

### 1. Terraform Configuration (`terraform.tfvars`)
```hcl
create_redis_node           = true
redis_instance_type         = "t3.micro"
redis_replica_count         = 3
redis_replica_instance_type = "t3.micro"
redis_master_name           = "mymaster"
```

### 2. Deploy Infrastructure
```bash
cd iaac/aws/terraform
terraform apply -var-file=terraform.tfvars
```

### 3. Application Master Discovery (Lazy Discovery)
In Redis Sentinel, **Sentinel does not push notifications to web servers**. Instead:
1. When a failover occurs, the app server's existing socket to the old primary drops with a `ConnectionError` or `ReadOnlyError`.
2. The `SentinelConnectionPool` in `django-redis` catches the error and queries the Sentinel endpoints (`REDIS_SENTINELS`) with `SENTINEL get-master-addr-by-name mymaster`.
3. Sentinel returns the IP of the newly promoted master, and the application updates its connection pool transparently.

### 4. Simulating AWS Failover & Inspecting Logs
To observe quorum agreement and leader election on AWS:

1. **Terminal 1 (Monitor Replica Sentinel Logs)**:
   SSH into one of the **Redis Replica** EC2 instances:
   ```bash
   sudo journalctl -u redis-sentinel -f
   ```
2. **Terminal 2 (Stop Primary)**:
   SSH into the **Redis Primary** EC2 instance:
   ```bash
   sudo systemctl stop redis-server
   ```
3. **Terminal 1 Log Stream**:
   Within 3 to 5 seconds, observe the consensus progression:
   ```text
   +sdown master mymaster 10.0.0.X 6379
   +odown master mymaster 10.0.0.X 6379 #quorum 2/2
   +try-failover master mymaster 10.0.0.X 6379
   +vote-for-leader <sentinel-id> 1
   +elected-leader master mymaster 10.0.0.X 6379
   +failover-state-select-slave master mymaster 10.0.0.X 6379
   +selected-slave slave 10.0.0.Y:6379
   +failover-state-send-slaveof-noone slave 10.0.0.Y:6379
   +switch-master mymaster 10.0.0.X 6379 10.0.0.Y 6379
   ```
4. **Terminal 3 (Watch App Reconnect to New Master)**:
   Run Sentinel monitor on any surviving Sentinel node:
   ```bash
   redis-cli -p 26379 MONITOR
   ```
   When web traffic hits the application, observe:
   ```text
   [0 10.0.0.AppIP:54322] "SENTINEL" "get-master-addr-by-name" "mymaster"
   ```
5. **Restart Old Primary**:
   ```bash
   sudo systemctl start redis-server
   ```
   Sentinel will automatically reconfigure the old primary into a replica:
   ```text
   +convert-to-slave slave 10.0.0.X:6379
   ```

---

## 6. Multi-Tier Caching & Workload Isolation (Next Steps)

To completely decouple distinct caching workloads:
1. **Tier 1 (In-Process Memory - `LocMemCache`)**:
   - Cache hot celebrity photo objects and metadata in local application container memory with a short 5-second TTL.
   - Eliminates redundant network round-trips to Redis and PostgreSQL during celebrity photo views.
2. **Tier 2 (Core Redis Sentinel)**:
   - Dedicated exclusively to atomic counters, user like sets, and distributed locks.
   - Shields critical application state from eviction pressure.
3. **Tier 3 (Dedicated Newsfeed Redis Deployment)**:
   - Newsfeed timeline lists (`feed:*`) generate high write and read churn.
   - Isolating newsfeed lists onto a dedicated Redis instance prevents timeline memory pressure from degrading like counters or triggering failovers.
