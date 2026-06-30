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

---

## Part 2: CloudWatch Metrics (Request & Database Latency)

Part 1 measured query bottlenecks offline using benchmark scripts. Part 2 makes the same data visible in production using CloudWatch Metrics. A custom Django middleware (`bses/metrics_middleware.py`) measures request latency, database latency, and query count on every HTTP request and outputs the data as CloudWatch Embedded Metric Format (EMF) JSON logs.

### What Gets Measured

On every request, the middleware logs:

| Metric | Description |
|--------|-------------|
| `RequestLatency` | Total time from request received to response sent (ms) |
| `DatabaseLatency` | Total time spent executing SQL queries during the request (ms) |
| `QueryCount` | Number of SQL queries fired during the request |

These are dimensioned by `Endpoint` (e.g. `/newsfeed/`, `/users/profile/alex_smith_0/`) and `Method` (GET/POST).

### Step 1: Deploy Updated Application to AWS

Push the latest code (with the metrics middleware) to the App EC2 instances. Rebuild the Docker image and restart:

```bash
ssh -i <your_key.pem> ubuntu@<APP_EC2_PUBLIC_IP>
cd systemdesignfromscratch/photoz
git pull origin main
docker compose -f docker-compose-app.yml up -d --build
```

### Step 2: Seed the Database on the DB Node

SSH into the DB EC2 instance and seed data:

```bash
ssh -i <your_key.pem> ubuntu@<DB_EC2_PUBLIC_IP>
cd systemdesignfromscratch
source photoz/venv/bin/activate
python chapter04/query_optimization/seed_data.py --reset
```

This creates 10,000 users with profiles. Each user has a predictable `username_display` and password.

### Step 3: Log In to the Photoz Website

Open the Photoz website in your browser (via the Load Balancer URL or App EC2 public IP).

Use any seeded user credentials to log in:

- **Username:** `alex_smith_0` (format is `{firstname}_{lastname}_{index}`)
- **Password:** `password123`

Other example usernames: `jordan_johnson_1`, `taylor_williams_2`, `morgan_brown_3`. The index goes from `0` to `9999`. First names and last names are randomly assigned from a fixed list, so the exact names will vary on each seed run. To find a valid username, query the database:

```bash
ssh -i <your_key.pem> ubuntu@<DB_EC2_PUBLIC_IP>
docker exec -it photoz-db psql -U postgres -d bses -c "SELECT username_display FROM users_userprofile LIMIT 5;"
```

### Step 4: Browse Pages to Generate Metrics

After logging in, browse the following pages to generate metric data points:

1. **Newsfeed** (`/newsfeed/`) -- fires ~83 queries per page load
2. **User profile** -- click on any username
3. **Photo detail** -- click on any photo
4. **Search** -- use the search bar to search for a name like "alex"

Each page load generates one EMF JSON log line in the container's stdout.

### Step 5: View Metrics in CloudWatch

1. Go to **AWS Console > CloudWatch > Metrics > All Metrics**
2. Look for the **PhotoZ/Application** namespace under Custom Namespaces
3. Click on **Endpoint, Method** dimension group
4. Select metrics to graph:
   - `RequestLatency` for `/newsfeed/` -- shows total request time
   - `DatabaseLatency` for `/newsfeed/` -- shows how much of that time is SQL
   - `QueryCount` for `/newsfeed/` -- shows number of queries per request

**How to read the graphs:**

- If `DatabaseLatency` is close to `RequestLatency`, the database is the bottleneck (most time is spent waiting for SQL).
- If `QueryCount` is high (80+), there are N+1 query problems that need `select_related`/`prefetch_related`.
- Compare metrics across endpoints: `/newsfeed/` will have significantly higher values than `/notifications/` or `/users/search/`.

**NOTE:** EMF metrics may take 1-2 minutes to appear in CloudWatch after the first log line is generated. If the `PhotoZ/Application` namespace does not appear, check that:
- The CloudWatch Logs agent (or Docker log driver) is forwarding container stdout to CloudWatch Logs
- The EC2 instance IAM role has `CloudWatchLogsFullAccess` policy attached (set up in Chapter 3 terraform)

### Viewing Raw EMF Logs

To see the raw JSON output without going to CloudWatch, check the container logs:

```bash
ssh -i <your_key.pem> ubuntu@<APP_EC2_PUBLIC_IP>
docker logs photoz-app 2>&1 | grep "PhotoZ/Application"
```

Example output (one line per request):
```json
{"_aws": {"Timestamp": 1719734400000, "CloudWatchMetrics": [{"Namespace": "PhotoZ/Application", "Dimensions": [["Endpoint", "Method"]], "Metrics": [{"Name": "RequestLatency", "Unit": "Milliseconds"}, {"Name": "DatabaseLatency", "Unit": "Milliseconds"}, {"Name": "QueryCount", "Unit": "Count"}]}]}, "Endpoint": "/newsfeed/", "Method": "GET", "StatusCode": 200, "RequestLatency": 124.56, "DatabaseLatency": 48.32, "QueryCount": 83}
```
