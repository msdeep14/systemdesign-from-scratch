# Execution Log - Chapter 04 (v0)

## Phase: Reproduce Query Bottlenecks (Date: 2026-06-19, Commit: be3ce8a0878e235c5c269770804783831b0da7f5, Model: Claude Opus 4.6 (Thinking))

**Analysis:** The photoz application has significant N+1 query problems across all major views. The newsfeed page is the worst offender -- a single page load fires **89 SQL queries** due to lazy-loading ForeignKey relationships in templates without `select_related` or `prefetch_related`. Combined with per-photo `COUNT(*)` queries for likes and comments (instead of using `annotate`), a single user browsing 5 pages fires ~160 queries total.

**Actions:**
- Created `chapter04/query_optimization/seed_data.py` -- seeds 500 users, 50 communities, 5000 photos, ~15K follows, 20K likes, 10K comments, 5K notifications in ~1.6s using `bulk_create`.
- Created `chapter04/query_optimization/benchmark_queries.py` -- replicates exact code paths from `views.py` + template access patterns, counts SQL queries per operation, categorizes query types, and runs `EXPLAIN ANALYZE` on key queries.
- Created `chapter04/README.md` -- documents how to run each script and what to look for in results.
- Created dummy image for seeded photos at `photoz/media/photos/seed/dummy.jpg`.

### Benchmark Results (BEFORE optimization)

**Summary: Query Count & Total DB Time**

| Operation | 500 Users (5k photos) | 10,000 Users (100k photos) |
|-----------|-----------------------|----------------------------|
| Newsfeed page load | 89 queries | 83 queries |
| Profile page | 44 queries | 44 queries |
| User search | 2 queries | 2 queries |
| Unread notification count | 1 query | 1 query |
| Photo detail page | 24 queries | 30 queries |
| **TOTAL (single user, 5 pages)** | **~160 queries** | **~160 queries** |

The number of queries fired is nearly identical (the N+1 query problem), but the execution time and database load change drastically at scale.

**Query Breakdown (Newsfeed -- 83-89 queries for a single page of 20 photos):**

```text
Base queries (feed, follows, communities, likes):  ~5
User lookups (N+1 per photo):       20
Profile lookups (N+1 per photo):    20
Community lookups (N+1 per photo):  0-6
Like COUNT (N+1 per photo):         20
Comment COUNT (N+1 per photo):      20
-----------------------------------------
TOTAL:                              83-89
```

**EXPLAIN ANALYZE -- What it is and how to use it:**

`EXPLAIN ANALYZE` is a PostgreSQL command that runs the query and shows how the database executed it. It answers two questions: (1) What plan did the database choose? (2) How long did each step take?

There are two versions:
- `EXPLAIN` (without ANALYZE): Shows the plan without running the query. Safe to run on production. Shows estimated costs only.
- `EXPLAIN ANALYZE`: Actually executes the query, so it shows real timing data. Use on dev/staging, or carefully on production (it runs the query and can be slow on large tables).

**How to run it from Django:**

Option 1 -- From a Django script (what our benchmark does):
```python
# In benchmark_queries.py (line 67-81)
def run_explain_analyze(queryset, label="Main query"):
    compiler = queryset.query.get_compiler(using='default')
    sql, params = compiler.as_sql()  # extract the raw SQL from the Django QuerySet

    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", params)
        rows = cursor.fetchall()
        for row in rows:
            print(f"   {row[0]}")
```
`queryset.query.get_compiler().as_sql()` extracts the raw SQL that Django would send to the database. We then prepend `EXPLAIN (ANALYZE, BUFFERS)` and run it directly. The `BUFFERS` option additionally shows how many disk pages were read (cache hits vs disk reads).

Option 2 -- From the psql shell directly:
```bash
psql -U photoz_user -d photoz_db
photoz_db=> EXPLAIN ANALYZE SELECT * FROM photos_photo ORDER BY created_at DESC LIMIT 20;
```

**How to read the output:**

Each line in the output is a "node" in the execution plan. The query planner builds a tree of operations. The deepest (most indented) nodes run first, and their results flow upward to the parent nodes.

Each node shows two sets of numbers:
```text
Seq Scan on photos_photo  (cost=17.60..280.10 rows=3502 width=66) (actual time=0.044..0.757 rows=491 loops=1)
                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                           ESTIMATED (before execution)              ACTUAL (measured during execution)
```

| Field | Meaning |
|-------|---------|
| `cost=17.60..280.10` | Estimated work. First number = startup cost (before first row is returned). Second number = total cost. These are abstract units, not milliseconds. |
| `rows=3502` | Estimated number of rows this step will produce. |
| `width=66` | Estimated average size (bytes) per row. |
| `actual time=0.044..0.757` | Measured wall time in milliseconds. First number = time to return the first row. Second number = time to return all rows. |
| `rows=491` | Actual number of rows produced. |
| `loops=1` | How many times this step was executed. In parallel plans or nested loops, this can be >1. Multiply time * loops to get the real total time. |

**Common node types and what they mean for optimization:**

| Node | Meaning | Optimization Signal |
|------|---------|-------------------|
| **Seq Scan** | Reads every row in the table from start to end. | Missing index. Acceptable for small tables (<1,000 rows). |
| **Index Scan** | Uses an index to jump directly to matching rows. | Good. This is what you want for filtered queries. |
| **Index Only Scan** | Reads data directly from the index without touching the table. | Best case. The index contains all the columns needed. |
| **Bitmap Index Scan + Bitmap Heap Scan** | Two-step: first scans the index to build a list of matching row locations, then reads those rows from the table. | Good for queries that match many rows (too many for a single Index Scan, too few for a Seq Scan). |
| **Sort** | Sorts rows in memory or on disk. | Check if an index on the ORDER BY column could avoid the sort entirely. |
| **Hash Join / Merge Join / Nested Loop** | Joins two tables. Hash Join builds a hash table. Merge Join requires sorted input. Nested Loop iterates row by row. | Nested Loop with a Seq Scan on the inner table is a red flag at large scale. |
| **Parallel Seq Scan** | Seq Scan split across multiple CPU workers. | Postgres auto-enables this for large tables. Still a sign that an index could help. |

---

**EXPLAIN ANALYZE results -- Newsfeed main query (top 20 photos):**

*With 500 Users (5,000 photos):*
```text
Limit  (cost=460.84..460.89 rows=20 width=66) (actual time=1.050..1.052 rows=20 loops=1)
  -> Sort  ...
        -> HashAggregate ...
              -> Seq Scan on photos_photo  (cost=17.60..280.10 rows=3502 width=66) (actual time=0.044..0.757 rows=491 loops=1)
Execution Time: 1.086 ms
```
Reading from inside out:
1. **Seq Scan on photos_photo**: Reads all 5,000 rows, filters down to 491 matching photos (photos from followed users, communities, or self). This is a full table scan because there is no index on `user_id` or `community_id`.
2. **HashAggregate**: Removes duplicates (from the `DISTINCT` in the Django query). Builds a hash table of unique photo IDs.
3. **Sort**: Sorts the 491 photos by `created_at DESC` to show newest first. Done in memory since the dataset is small.
4. **Limit**: Takes only the first 20 rows (page 1).

Key observation: **Seq Scan on photos_photo** -- the database scans all 5,000 rows and filters down to matching photos. No index on `created_at` for the `ORDER BY`, and no index on `user_id + community_id` for the filter.

*With 10,000 Users (100,000 photos):*
```text
Limit  (cost=7593.82..7596.40 rows=20 width=65) (actual time=5.685..6.345 rows=20 loops=1)
  ->  Unique ...
        ->  Gather Merge ...
              Workers Planned: 1
              Workers Launched: 1
              ->  Sort ...
                    ->  Parallel Seq Scan on photos_photo  (cost=13.35..3436.76 rows=41188 width=65) (actual time=0.079..4.431 rows=200 loops=2)
Execution Time: 6.364 ms
```
Reading from inside out:
1. **Parallel Seq Scan**: Two workers (`loops=2`) each scan half the table (~50,000 rows each), filtering down to ~200 matching rows each. 
2. **Sort**: Each worker sorts its results by `created_at DESC`.
3. **Gather Merge**: Merges the sorted results from both workers into a single sorted stream.
4. **Unique**: Removes duplicates.
5. **Limit**: Takes first 20 rows.

Key observation: **Parallel Seq Scan on photos_photo** -- execution time jumped significantly (6x slower).

**Why did PostgreSQL shift from a Seq Scan to a Parallel Seq Scan?**
PostgreSQL uses a "Query Planner" which relies on cost-based optimization. Before running a query, it calculates a math score (the "cost") based on table size, disk reading speed, and CPU effort. 
- At 5,000 photos, the table is small. The time required to start background workers for a parallel query is higher than just reading the table sequentially on a single thread.
- At 100,000 photos, the table crosses a minimum size threshold (`min_parallel_table_scan_size`, default 8MB). The query planner determines that reading the table sequentially is now too slow, so the overhead of starting multiple workers is worth the performance gain. It automatically switches to a `Parallel Seq Scan`.

**EXPLAIN ANALYZE -- User search for 'alex':**

*With 500 Users:*
```text
Seq Scan on users_userprofile  ... (actual time=0.006..0.286 rows=19 loops=1)
Execution Time: 0.291 ms
```

*With 10,000 Users:*
```text
Seq Scan on users_userprofile  ... (actual time=0.021..3.844 rows=375 loops=1)
Execution Time: 3.856 ms
```
Key observation: Full **Seq Scan** with `UPPER(...) LIKE` pattern matching. No trigram index. With 10,000 users, execution time increases by over 13x, scaling linearly and becoming a bottleneck at larger datasets.

**Edge Cases:**
- Fixed Postgres modulo operator issue in seed script -- Django's `cursor.execute` uses psycopg2 parameterization, not Python `%` formatting. Used `MOD()` function instead.
- Removed all emojis from code and print statements per project coding standards.
- **OOM Crash on t3.micro (Debugging & Fix):**
  - **Issue:** Running the massive `seed_data.py` on a 1GB `t3.micro` EC2 instance caused the Postgres server to abruptly crash with `psycopg2.OperationalError: server closed the connection unexpectedly`. When attempting to rerun the script immediately after, a secondary error occurred: `FATAL: the database system is in recovery mode`.
  - **Debugging Steps:** To confirm if the crash was caused by the OS terminating the process due to lack of memory, we checked the Linux kernel ring buffer on the DB EC2 instance using `sudo dmesg -T | grep -i -E 'oom|killed process'`. The output confirmed the OOM killer intervened:
    ```text
    [Wed Jul  1 04:25:31 2026] oom-kill:constraint=CONSTRAINT_NONE... task=postgres,pid=3154,uid=999
    [Wed Jul  1 04:25:31 2026] Out of memory: Killed process 3154 (postgres) total-vm:526664kB, anon-rss:295264kB...
    ```
    Postgres was killed by the OS. The secondary `recovery mode` error occurred because Docker's `restart: always` policy immediately rebooted the container, but Postgres needed time to replay its Write-Ahead Logs (WAL) before accepting new connections.
  - **The Fix:** The script held ~100,000 `Photo` and ~300,000 `Follow` massive Django ORM objects in Python memory before calling `bulk_create`. This caused Postgres and Python to compete for the 1GB of RAM, triggering the OOM kill. We fixed this by:
    1. Chunking the ORM creation and flushing `bulk_create` to the database every 10,000 objects across all heavy tables (`photos`, `follows`, `likes`, `comments`, `notifications`).
    2. Optimizing downstream functions to accept lists of integer IDs rather than passing around massive lists of heavy Django model instances (reducing memory overhead from ~150MB down to ~1MB).
    3. Manually wiping the corrupted Docker volume (`docker compose down -v`) and re-running migrations to quickly bypass the lengthy WAL recovery process.

---

## Phase: CloudWatch EMF Metrics Middleware (Date: 2026-06-30, Commit: 0d17852e38ff966e51b6ae0c6d828dae46535d4b, Model: Gemini 3.1 Pro (High))

**Analysis:** The benchmark scripts provide offline analysis of query counts and DB latency per endpoint. To get the same visibility in production (without `DEBUG=True` or EXPLAIN ANALYZE overhead), we need a lightweight middleware that measures request and database latency on every request and outputs the data as structured logs.

**Why EMF instead of PutMetricData API?**
The alternative approach is to call the AWS `cloudwatch:PutMetricData` API directly from the middleware (using `boto3`). We chose EMF over this for three reasons:
1. **No added latency.** `PutMetricData` is an HTTP API call to AWS. On every request, the middleware would make a network round-trip to the CloudWatch API endpoint, adding 5-20ms of latency to every user request. EMF just writes a log line to stdout, which is a local in-memory operation with near-zero overhead.
2. **No extra IAM permissions.** `PutMetricData` requires the `cloudwatch:PutMetricData` permission. EMF reuses the existing `CloudWatchLogsFullAccess` policy that is already attached to the EC2 IAM role from Chapter 3. The metric extraction happens server-side inside AWS when CloudWatch Logs receives the structured JSON.
3. **No extra dependencies.** `PutMetricData` requires the `boto3` SDK in the application container. EMF only requires `json.dumps()` from Python's standard library.
4. **No AWS SDK dependency in application code.** `PutMetricData` requires importing `boto3` and calling AWS APIs directly from the middleware, tightly coupling the Django application to AWS. With EMF, the application only uses `json.dumps()` from Python's standard library. The metric data (e.g., `QueryCount`, `RequestLatency`) is just plain JSON fields. If the system later migrates away from AWS, only the **log pipeline** needs to change (swap Docker's `awslogs` driver for FluentBit/Promtail configured to extract the JSON fields) — the application code stays untouched. Note: the `_aws` and `CloudWatchMetrics` keys in the EMF JSON are AWS-proprietary. Other tools like Promtail or Grafana cannot automatically interpret this structure. They would need custom configuration to extract the raw JSON metric fields.
5. **Lower cost at scale.** Both approaches create the same custom metrics ($0.30/metric/month), but the transport cost differs significantly. `PutMetricData` charges $0.01 per 1,000 API calls — at 100 req/s that's ~8.6M calls/day (~$86/day). EMF piggybacks on CloudWatch Logs ingestion at $0.50/GB — each EMF line is ~500 bytes, so at 100 req/s that's ~4.3 GB/day (~$2.15/day). At production scale, PutMetricData is roughly **40x more expensive** for metric transport.

**Approach:** CloudWatch Embedded Metric Format (EMF). The middleware logs a JSON object to stdout on every request. When the Docker container sends these logs to CloudWatch Logs, AWS automatically extracts the metrics (no extra agents or API calls needed).

**Actions:**
- Created `photoz/bses/metrics_middleware.py` -- uses Django's `connection.execute_wrapper()` to wrap every SQL call and measure DB latency and query count per request. Outputs EMF JSON with `RequestLatency`, `DatabaseLatency`, and `QueryCount` metrics under the `PhotoZ/Application` namespace, dimensioned by `Endpoint` and `Method`.
- Updated `photoz/bses/settings.py` -- added `json_raw` formatter (outputs raw message without timestamp/level prefix), `metrics_console` handler, and `metrics` logger. Registered `CloudWatchMetricsMiddleware` at the end of the MIDDLEWARE list.
- Verified middleware imports correctly with Django setup.

**Example EMF log output (one line per request):**
```json
{"_aws": {"Timestamp": 1719734400000, "CloudWatchMetrics": [{"Namespace": "PhotoZ/Application", "Dimensions": [["Endpoint", "Method"]], "Metrics": [{"Name": "RequestLatency", "Unit": "Milliseconds"}, {"Name": "DatabaseLatency", "Unit": "Milliseconds"}, {"Name": "QueryCount", "Unit": "Count"}]}]}, "Endpoint": "/newsfeed/", "Method": "GET", "StatusCode": 200, "RequestLatency": 124.56, "DatabaseLatency": 48.32, "QueryCount": 83}
```

---

## Phase: CloudWatch EMF Middleware - High Cardinality Fix (Date: 2026-07-01, Commit: 408c39b4d1c99f254f3025f85b7798212a3784c8, Model: Claude Opus 4.6 (Thinking))

**Analysis:** After successfully executing the seed script and logging in, we observed that CloudWatch metrics were not graphing correctly. The EMF logs showed high cardinality dimensions where the endpoint was logged as the exact URL path (e.g., `/users/phoenix_jackson_0/`). This created a unique metric for every single user profile, breaking CloudWatch's ability to aggregate metrics into a single line graph.

**Approach:** Rather than logging `request.path` directly, we updated the middleware to capture Django's parameterized route pattern (e.g., `/users/<str:username>/`).

**Actions:**
- Updated `photoz/bses/metrics_middleware.py`. Added logic to fall back to `request.path` only if `request.resolver_match` is empty, otherwise extract the logical view name via `request.resolver_match.view_name`. This properly resolves Django's nested URL inclusions (which `route` truncates), correctly grouping all identical endpoint paths into clean dimensions like `newsfeed`, `login`, and `profile`, making the data properly visible on CloudWatch graphs.

---

## Phase: Newsfeed N+1 Query Fix (Date: 2026-07-04, Commit: pending, Model: Claude Opus 4.6 (Thinking))

**Analysis:** The newsfeed page fires 87 SQL queries per page load (20 photos). 80 of those are N+1 queries triggered by the template loop accessing lazy-loaded ForeignKey relationships (`photo.user`, `photo.user.profile`, `photo.community`) and calling `.count()` on related managers (`photo.likes.count`, `photo.comments.count`). Production CloudWatch metrics confirmed: 87 queries, ~128ms DB latency, 230-635ms request latency (1,439ms on cold start).

**Approach:** Two changes:
1. Add `select_related('user__profile', 'community')` to the feed QuerySet in `views.py`. This tells Django to JOIN the `auth_user`, `users_userprofile`, and `communities_community` tables in a single SQL query instead of lazy-loading them one by one inside the template loop. Eliminates ~45 N+1 queries (20 user lookups + 20 profile lookups + ~5 community lookups).
2. Add `annotate(likes_count=Count('likes', distinct=True), comments_count=Count('comments', distinct=True))` to compute like and comment counts inside the database in the same query. The template then reads `photo.likes_count` (a pre-computed integer attribute) instead of calling `photo.likes.count()` (which fires a new `SELECT COUNT(*)` query). Eliminates 40 N+1 queries (20 likes + 20 comments). The `distinct=True` is required because `select_related` with multiple JOINs can produce duplicate rows, which would inflate the counts without it.

**Actions:**
- Modified `photoz/newsfeed/views.py` -- added `select_related('user__profile', 'community')` and `annotate(likes_count=..., comments_count=...)` to the feed QuerySet. Added `Count` import.
- Modified `photoz/newsfeed/templates/newsfeed/feed.html` -- replaced `{{ photo.likes.count }}` with `{{ photo.likes_count }}` and `{{ photo.comments.count }}` with `{{ photo.comments_count }}`.

**Expected result:** 87 queries -> ~7 queries per newsfeed page load.
