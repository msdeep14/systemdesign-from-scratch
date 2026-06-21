# Chapter 4: Database Bottlenecks, Read Replicas & Caching

Chapter 3 solved the **compute** bottleneck (CPU exhaustion, slow I/O). This chapter tackles the **data** bottleneck. The database becomes the next single point of failure as the application scales.

---

## Part 1: Query Optimization

Located in `query_optimization/`, these scripts expose the N+1 query problem and missing database indexes in the Photoz application.

### Prerequisites

Activate the Python virtual environment:

```bash
source photoz/venv/bin/activate
```

**Option A: Local database (Docker)**

Use the standalone database compose file to spin up just Postgres:

```bash
cd photoz
docker compose -f docker-compose-db.yml up -d
```

This uses `photoz/.env` for credentials (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`). The database is exposed on `localhost:5432`.

**Option B: Remote database (EC2)**

If the database is running on a remote EC2 instance (e.g. from the Chapter 3 decoupled architecture), set the connection details via environment variables. The credentials should match what's configured in `photoz/.env` on the DB node:

```bash
export POSTGRES_HOST=<DB_EC2_PRIVATE_IP>
export POSTGRES_USER=<your_db_user>
export POSTGRES_PASSWORD=<your_db_password>
export POSTGRES_DB=<your_db_name>
```

Make sure port 5432 is reachable from your machine (check the Security Group rules on the DB EC2 instance -- it should allow inbound 5432 from your IP or the App node's Security Group).

**Option C: SSH into the DB EC2 instance**

SSH into the EC2 instance where the DB docker container is running and execute the scripts directly there. The repo is already cloned on the instance from Chapter 3 setup. Since the DB container maps port 5432 to the host, the scripts connect to `localhost:5432` by default -- no need to open port 5432 externally.

```bash
ssh -i <your_key.pem> ubuntu@<DB_EC2_PUBLIC_IP>
cd systemdesignfromscratch
source photoz/venv/bin/activate
python chapter04/query_optimization/seed_data.py --reset
python chapter04/query_optimization/benchmark_queries.py
```

The scripts use Django's ORM internally to interact with the database models, so the Python virtual environment with Django and other project dependencies (`psycopg2`, `Pillow`, etc.) must be set up. If the virtual environment is not set up on the EC2 instance, create it first:

```bash
cd photoz
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**NOTE:** The results from local database or on remote database are almost same but on remote database it will be slightly slower due to network latency. The difference will be in milliseconds but it will give you an idea of how the application will behave under load. The Part 1 focuses on query optimization, so running the sample scripts at any place is fine.

### Step 1: Seed the Database

**NOTE:** You can skip database prefill if there is already data in the database. Refer to flags `--reset` and `--force` to understand how to use this script.

Populates Postgres with realistic volume: 10,000 users, 100,000 photos, 400,000 likes, 200,000 comments, ~300,000 follow relationships, and 100,000 notifications.

**Local:**
```bash
python chapter04/query_optimization/seed_data.py --reset
```

**Remote EC2:**
```bash
POSTGRES_HOST=<DB_EC2_PRIVATE_IP> python chapter04/query_optimization/seed_data.py --reset
```

Flags:
- `--reset` -- Clears all existing data before seeding.
- `--reset-only` -- Clears all existing data and exits immediately without seeding new data.
- `--force` -- Seeds additional data on top of existing data.

**Expected output:** Each step prints its completion time. Locally the full seed should finish in under 30 seconds. Against a remote EC2 database it will be slower due to network latency.

### Step 2: Run the Query Benchmark (BEFORE optimization)

Replicates the exact code paths from `views.py` and Django template rendering to count every SQL query fired per page load.

**Local:**
```bash
python chapter04/query_optimization/benchmark_queries.py
```

**Remote EC2:**
```bash
POSTGRES_HOST=<DB_EC2_PRIVATE_IP> python chapter04/query_optimization/benchmark_queries.py
```

Use `--verbose` to print every single SQL query instead of the first 15.

### What to Look For in the Results

The benchmark runs 5 tests and prints a summary table at the end. Key things to pay attention to:

**1. Newsfeed Page Load (BENCHMARK 1)**

This is the worst offender. Look at the "SQL queries fired" number -- it should be around **85-90 queries** for a single page of 20 photos. The "Query breakdown by type" section shows exactly why:

- **User lookups (N+1):** One `SELECT auth_user.*` query per photo because `photo.user` is a lazy ForeignKey load.
- **Profile lookups (N+1):** One `SELECT users_userprofile.*` per photo because `photo.user.profile` is another lazy load.
- **Like COUNT (N+1):** One `SELECT COUNT(*) FROM photos_like` per photo because the template calls `photo.likes.count()`.
- **Comment COUNT (N+1):** Same pattern for comments.

The EXPLAIN ANALYZE at the bottom shows the main feed query doing a **Seq Scan** on `photos_photo` (scanning every row instead of using an index).

**2. Profile Page (BENCHMARK 2)**

Similar N+1 pattern -- each photo on the profile triggers individual `COUNT(*)` queries for likes and comments. Look for the query count scaling linearly with the number of photos.

**3. User Search (BENCHMARK 3)**

Only 2 queries, but the EXPLAIN ANALYZE shows a **Seq Scan** with `UPPER(...) LIKE` pattern matching. With 10,000 users this is fast, but at 500,000 users this sequential scan becomes a real bottleneck.

**4. Unread Notification Count (BENCHMARK 4)**

Just 1 query, but this runs on **every single page load** for every authenticated user (it's in a Django context processor). At scale, this adds up -- 1 extra query per page load across millions of requests creates significant unnecessary load on the database.

**5. Photo Detail Page (BENCHMARK 5)**

N+1 on comment authors -- each comment triggers a separate `SELECT auth_user.*` and `SELECT users_userprofile.*` to display the commenter's name.

**Summary Table**

The final summary shows the total query count across all 5 pages. The key number:

> A single user browsing 5 pages fires ~160 SQL queries.
> With 100 concurrent users, that's ~16,000 queries hitting Postgres.

### Benchmark Results

Full benchmark output is captured in `execution-v0.md`.

