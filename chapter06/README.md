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
