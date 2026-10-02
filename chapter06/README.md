# Chapter 6 Benchmarks: Asynchronous Processing

Identification and fixing asynchronous processing bottlenecks in the Photoz architecture.

## Setup & Benchmarks

To expose and test the asynchronous processing bottlenecks, run the following steps.

### 1. Seed Celebrity Users
Creating "celebrity" accounts with a large number of followers.
*(Note: This creates `@celeb_500k`, `@celeb_1m`, and `@celeb_2m` with the password `password123`. It takes several minutes to run as we bulk create users in batches to avoid locking the database and impacting live traffic.)*

From the `photoz/` directory, run the command inside the `web` container. For AWS, run the command on one of EC2 app node:
```bash
docker-compose exec web python manage.py seed_celebrity_users
```

### 2. Run Upload Benchmark
To observe the fan-out bottleneck, run the benchmarking script which logs in as each celebrity and simulates an image upload.

#### Running Locally
From the project root directory, point the script to your local server (make sure venv is activated):
```bash
python chapter06/benchmarks/upload_timing.py
```

#### Running on AWS
From your local machine, run the script and point it to your AWS load balancer's IP or domain:
```bash
python chapter06/benchmarks/upload_timing.py --host http://<your-load-balancer-ip>
```

### What to Look For in Logs
While the benchmark is running, check your terminal running `docker-compose up` or the local Gunicorn instance. 
Look for JSON metrics output containing `RequestLatency` and `DatabaseLatency`.

To easily filter these logs, you can run (inside photoz/ directory):
```bash
docker-compose logs -f web | grep "RequestLatency"
```
For the synchronous fan-out implementation, you will observe extremely high request latency or Gunicorn timeout errors (which defaults to taking longer than 120s for `@celeb_1m` and `@celeb_2m`).

---

## Hybrid Push/Pull Implementation

The fix introduces a `follower_count` field on `UserProfile`. Users above 10,000 followers (celebrities) are skipped during write-time fan-out. Their photos are pulled at read time and merged into the feed.

### 1. Apply Migration

Run inside the `web` container (from `photoz/`):
```bash
docker-compose exec web python manage.py makemigrations
docker-compose exec web python manage.py migrate
```

### 2. Backfill Follower Counts

The existing `Follow` rows from the seeding script were created via `bulk_create`, which bypasses Django signals, so `follower_count` is `0` for all existing users. Run the backfill once:
```bash
docker-compose exec web python manage.py backfill_follower_counts
```
This recomputes follower counts from the `Follow` table and updates `UserProfile.follower_count` in batches. Expect this to take 1-2 minutes for 2M users.

### 3. Restart the Web Container

New Python code requires a container restart to take effect:
```bash
docker-compose restart web
```

### 4. Re-run Upload Benchmark

After the migration and backfill:
```bash
python chapter06/benchmarks/upload_timing.py
```
All three celebrity uploads should now complete in under 1 second. Feed loads for followers of celebrities will show celebrity photos merged in at read time.

### What to Look For

- Upload latency: drops from 30s+ / timeout → <1s for all celebrities.
- On a follower's feed load: one additional DB query for celebrity photos (`SELECT ... WHERE user_id IN (...)`). Check `DatabaseLatency` in logs — this should be a small, fast query.

---

## Follower Count Hot Row Benchmark

If thousands of users try to follow a celebrity at the exact same time, they all queue up for a lock on the exact same row in the `UserProfile` table.

### 1. Run the Hot Row Benchmark

script simulating real users attempting to follow `@celeb_2m` simultaneously.

Run this command from the project root (`systemdesignfromscratch/`):
```bash
python chapter06/benchmarks/follow_timing.py --host http://localhost --concurrency 200
```

### 2. Prove the DB Lock is the Limiting Factor

Even locally, you can prove that the database lock limits throughput by comparing a scattered workload (hitting different rows) against a concentrated workload (hitting the same row).

```bash
python chapter06/benchmarks/compare_hot_row.py --host http://<your-alb-dns> --concurrency 5000
```

### 3. Visualize the New Architecture (Celery + Redis)

To solve the Hot Row, we are introducing **Celery** (Workers) and **Celery Beat** (Scheduler) using **Redis** as the message broker. 

We have updated the system's C4 Architecture Diagram (Structurizr) to reflect this new deployment view (specifically mapping both the Celery Worker and Celery Beat to the App Auto Scaling Group, utilizing celery-redbeat for distributed scheduling).

To view the updated architectural diagrams in your browser:

1. Navigate to the `photoz` directory.
2. Start the Structurizr Lite container mapping the `structurizr` folder:
   ```bash
   cd photoz
   docker run -it --rm -p 8080:8080 -v $(pwd)/structurizr:/usr/local/structurizr structurizr/structurizr local
   ```
3. Open [http://localhost:8080](http://localhost:8080) in your browser and view the "System Context" and "Container" views.

**FINOS CALM (Architecture as Code)**

We have also updated the FINOS CALM architecture model (`photoz/architecture/photoz.calm.json`) to serve as our compliance ground truth. 

To visualize the CALM architecture diagram locally (requires Node.js):
```bash
cd photoz
# Validate the new architecture against our guardrails
calm validate -a architecture/photoz.calm.json -p architecture/guardrails.pattern.json

# Generate and serve the interactive documentation site
calm docify -a architecture/photoz.calm.json -o architecture/docs
cd architecture/docs
npm install
npm run start
```

### 4. Inspecting Celery Health & Distributed Scheduling (RedBeat)

With Celery and RedBeat running in our App cluster, you can verify their health, observe the leader election, and inspect the Redis lock directly.

**Check Celery Worker Health**
Run this to ping the workers and verify they are listening to the Redis queues:
```bash
docker compose exec celery celery -A bses inspect ping
docker compose exec celery celery -A bses inspect active
```

**Observe RedBeat Leader Election**
Since we are using `celery-redbeat` for distributed scheduling, check the logs of your Celery Beat instances. Only one instance will successfully acquire the lock and dispatch tasks:
```bash
docker compose logs celery-beat
```
*You should see logs indicating RedBeat "acquiring lock" and "waking up".*

**Identify the Redis Lock**
You can connect directly to Redis to see the lock key and the task definitions that RedBeat stores.

**Locally:** Run these from the `photoz/` directory on your machine:
```bash
# List all RedBeat keys in Redis
docker compose exec redis redis-cli -n 1 KEYS "redbeat:*"

# Check which instance currently holds the distributed lock
docker compose exec redis redis-cli -n 1 GET "redbeat::lock"

# Inspect the stored schedule for our flush task
docker compose exec redis redis-cli -n 1 HGETALL "redbeat:flush_follower_counts_task"
```

**On AWS Infrastructure:**
SSH into your dedicated Redis Node and run `redis-cli` directly. Note the `-n 1` flag is required because our application connects to Redis Database 1 (via `REDIS_URL=redis://...:6379/1`):
```bash
redis-cli -n 1 KEYS "redbeat:*"
redis-cli -n 1 GET "redbeat::lock"
redis-cli -n 1 HGETALL "redbeat:flush_follower_counts_task"
```

---

## Likes Hot Row Benchmark

When many users like the same photo at the same time, every request runs:
```sql
UPDATE photos_photo SET likes_count = likes_count + 1 WHERE id = ?
```
Each update acquires an exclusive row lock. Concurrent requests queue behind each other, causing latency to spike even though the database is otherwise idle.

The benchmark mirrors `compare_hot_row.py`:
- **Scattered phase**: Each worker uploads their own photo and likes it. Every like hits a different row — true zero contention.
- **Hot row phase**: All workers like a single celebrity photo. Every like hits the same row — full serialization.

### 1. Get a Celebrity Photo ID

SSH into any app node and run:
```bash
sudo docker exec -it photoz-web-1 python manage.py shell -c \
  "from photos.models import Photo; from django.contrib.auth.models import User; u = User.objects.get(username='celeb_2m'); p = Photo.objects.filter(user=u).first(); print(p.id if p else 'No photos — create one first')"
```

If no photo exists for the celebrity, create one:
```bash
sudo docker exec -it photoz-web-1 python manage.py shell -c \
  "from photos.models import Photo; from django.contrib.auth.models import User; u = User.objects.get(username='celeb_2m'); p = Photo.objects.create(user=u, image='placeholder.jpg', caption='Hot row benchmark'); print('Created photo id:', p.id)"
```

### 2. Run the Benchmark Locally

From the project root, with venv activated:
```bash
python chapter06/benchmarks/benchmark_likes_hot_row.py \
  --host http://localhost \
  --concurrency 300 \
  --hot-photo-id <celebrity_photo_id>
```

### 3. Run the Benchmark on AWS

From your local machine:
```bash
python chapter06/benchmarks/benchmark_likes_hot_row.py \
  --host http://<your-load-balancer-ip> \
  --concurrency 500 \
  --hot-photo-id <celebrity_photo_id>
```

The script handles everything: it signs up N users, uploads one photo per user (for the scattered phase), then runs both phases automatically.

### What to Look For

| Phase | Expected Behaviour |
|---|---|
| Scattered (own photos) | Fast — each request hits a different row, no lock wait |
| Hot Row (celebrity photo) | Slower total time, requests serializing behind the row lock |

To observe the lock queue in real time during the hot row phase:
```bash
sudo docker exec -it photoz-db-1 psql -U postgres -d bses -c \
  "SELECT pid, state, wait_event_type, wait_event, query FROM pg_stat_activity WHERE state != 'idle' ORDER BY wait_event_type;"
```
You will see multiple connections in `Lock` wait state, all blocked on the same `UPDATE`.

---

## Celery Fanout Bottleneck (Worker Starvation)

When a "Power User" (a user with thousands of followers, but just under the celebrity threshold) uploads a photo, our current architecture uses a Celery task to asynchronously push the photo ID into every follower's Redis feed.

If a user has 9,999 followers, the Celery worker executes a synchronous loop, performing 9,999 sequential `LPUSH` network calls to Redis.

### 1. Run the Fanout Benchmark

This benchmark script simulates concurrent power users uploading photos to expose how a long-running synchronous network loop blocks Celery workers.

**Running Locally:**
```bash
python chapter06/benchmarks/benchmark_celery_fanout.py \
  --concurrency 4
```

**Running on AWS:**
To run the script from local machine, update security groups for postgres to allow 5432 port for your ip and 6379 port for redis sg for your ip.
```bash
python chapter06/benchmarks/benchmark_celery_fanout.py \
  --host http://<your-load-balancer-ip> \
  --redis-host <redis-ec2-ip> \
  --db-host <db-ec2-ip> \
  --db-password <your-postgres-password> \
  --concurrency 15
```

### 2. Analyze the Bottleneck (Worker Starvation)

When we run the benchmark with varying concurrency, we observe the following results:

**Concurrency = 4:**
```
Total concurrent uploads: 4
Total followers fanned out to: 39996
Total time taken by Celery Workers: 8.23 seconds
Throughput: 4861 Redis LPUSH operations per second
```

**Concurrency = 15 (Without Pipelining):**
```
Total concurrent uploads: 15
Total followers fanned out to: 149985
Total time taken by Celery Workers: 39.06 seconds
Throughput: 3840 Redis LPUSH operations per second
```

### 3. Step 1 Fix: Redis Pipelining

By wrapping the sequential `LPUSH` commands inside a `redis_client.pipeline()`, we batch all network commands into a single TCP round-trip. Re-running the benchmark yields a massive latency reduction:

**Concurrency = 15 (With Pipelining):**
```
Total concurrent uploads: 15
Total followers fanned out to: 149985
Total time taken by Celery Workers: 3.51 seconds
Throughput: 42698 Redis LPUSH operations per second
```

**Note on Postgres Replication Lag:** 
Because the benchmark performs a massive `bulk_create` of 150,000 follow edges directly to the Postgres Primary, and the Celery worker immediately reads from the Postgres Replica, there is a risk of replication lag. If the worker queries the replica before the edges synchronize, it will see 0 followers and incorrectly succeed instantly. A 15-second `time.sleep()` is injected into the benchmark script to allow the replica to catch up before triggering the uploads.

