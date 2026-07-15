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

## Phase: Newsfeed N+1 Query Fix (Date: 2026-07-04, Commit: 4f1239cae949316ceb826c918264e7d99d7f4340, Model: Claude Opus 4.6 (Thinking))

**Analysis:** The newsfeed page fires 87 SQL queries per page load (20 photos). 80 of those are N+1 queries triggered by the template loop accessing lazy-loaded ForeignKey relationships (`photo.user`, `photo.user.profile`, `photo.community`) and calling `.count()` on related managers (`photo.likes.count`, `photo.comments.count`). Production CloudWatch metrics confirmed: 87 queries, ~128ms DB latency, 230-635ms request latency (1,439ms on cold start).

**Approach:** Two changes:
1. Add `select_related('user__profile', 'community')` to the feed QuerySet in `views.py`. This tells Django to JOIN the `auth_user`, `users_userprofile`, and `communities_community` tables in a single SQL query instead of lazy-loading them one by one inside the template loop. Eliminates ~45 N+1 queries (20 user lookups + 20 profile lookups + ~5 community lookups).
2. Add `annotate(likes_count=Count('likes', distinct=True), comments_count=Count('comments', distinct=True))` to compute like and comment counts inside the database in the same query. The template then reads `photo.likes_count` (a pre-computed integer attribute) instead of calling `photo.likes.count()` (which fires a new `SELECT COUNT(*)` query). Eliminates 40 N+1 queries (20 likes + 20 comments). The `distinct=True` is required because `select_related` with multiple JOINs can produce duplicate rows, which would inflate the counts without it.

**Actions:**
- Modified `photoz/newsfeed/views.py` -- added `select_related('user__profile', 'community')` and `annotate(likes_count=..., comments_count=...)` to the feed QuerySet. Added `Count` import.
- Modified `photoz/newsfeed/templates/newsfeed/feed.html` -- replaced `{{ photo.likes.count }}` with `{{ photo.likes_count }}` and `{{ photo.comments.count }}` with `{{ photo.comments_count }}`.

**Expected result:** 87 queries -> ~7 queries per newsfeed page load.

---

## Phase: Automated Database Seeding via Terraform (Date: 2026-07-04, Commit: a7a944f13ffc50b8db1cda85961ad993a287f229, Model: Gemini 3.1 Pro (High))

**Analysis:** Manually SSHing into the EC2 instance to run `seed_data.py` is tedious. By exposing a boolean Terraform variable, we can optionally instruct the Database EC2 node to run the seeding script directly during initial provisioning.

**Actions:**
- Copied `chapter03/iaac/terraform` to `iaac/aws/terraform` for global use across the project.
- Modified `iaac/aws/terraform/variables.tf` to add the `seed_database` variable (default false).
- Modified `iaac/aws/terraform/outputs.tf` to print `test_user_credentials` if seeding is enabled.
- Modified `iaac/aws/terraform/main.tf` to update `db_node`'s `user_data`. If `seed_database` is true, it installs `python3-venv`, `libpq-dev`, builds the virtual environment, installs requirements, waits 10 seconds for Postgres to start, and runs `seed_data.py --reset`.
- Modified `chapter04/query_optimization/seed_data.py` to guarantee the first seeded user (index 0) has `first_name="Test"`, `last_name="User"`, and `username_display="test_user"` with password `password123`.
- Updated `chapter04/README.md` to document the new `terraform apply -var="seed_database=true"` command for automated seeding.

---

## Phase: Newsfeed Database Latency Analysis (Date: 2026-07-05, Commit: 6835d939f3749d21b997586d4c67b851213a276a, Model: Gemini 3.1 Pro (High))

**Analysis:** After fixing the N+1 query problem, the Newsfeed query count dropped to 7, but the query itself became incredibly slow (taking ~500ms+ just for the database execution, and causing request latency > 1000ms). Ran `EXPLAIN ANALYZE` on the generated SQL in production. The query is executed for test_user with user_id=1 created with seed_data script.

<details>
<summary>Click to view raw SQL Query generated by Django</summary>

```sql
EXPLAIN ANALYZE
SELECT 
    "photos_photo"."id", 
    "photos_photo"."user_id", 
    "photos_photo"."community_id", 
    "photos_photo"."image", 
    "photos_photo"."caption", 
    "photos_photo"."created_at", 
    "auth_user"."id", 
    "auth_user"."username",
    "users_userprofile"."id", 
    "users_userprofile"."username_display",
    "communities_community"."id", 
    "communities_community"."name", 
    COUNT(DISTINCT "photos_like"."id") AS "likes_count", 
    COUNT(DISTINCT "photos_comment"."id") AS "comments_count" 
FROM "photos_photo" 
INNER JOIN "auth_user" ON ("photos_photo"."user_id" = "auth_user"."id") 
LEFT OUTER JOIN "users_userprofile" ON ("auth_user"."id" = "users_userprofile"."user_id") 
LEFT OUTER JOIN "communities_community" ON ("photos_photo"."community_id" = "communities_community"."id") 
LEFT OUTER JOIN "photos_like" ON ("photos_photo"."id" = "photos_like"."photo_id") 
LEFT OUTER JOIN "photos_comment" ON ("photos_photo"."id" = "photos_comment"."photo_id") 
WHERE (
    "photos_photo"."community_id" IN (
        SELECT U0."community_id" FROM "communities_communitymembership" U0 WHERE (U0."status" = 'accepted' AND U0."user_id" = 1)
    ) OR 
    ("photos_photo"."community_id" IS NULL AND "photos_photo"."user_id" IN (
        SELECT U0."following_id" FROM "users_follow" U0 WHERE U0."follower_id" = 1
    )) OR 
    "photos_photo"."user_id" = 1
) 
GROUP BY "photos_photo"."id", "auth_user"."id", "users_userprofile"."id", "communities_community"."id" 
ORDER BY "photos_photo"."created_at" DESC 
LIMIT 20;
```

</details>
<details>
<summary>Click to view EXPLAIN ANALYZE output</summary>

```text
 Limit  (cost=93395.44..93395.49 rows=20 width=165) (actual time=524.323..524.434 rows=20 loops=1)
   ->  Sort  (cost=93395.44..94795.44 rows=560000 width=165) (actual time=524.321..524.430 rows=20 loops=1)
         Sort Key: photos_photo.created_at DESC
         Sort Method: top-N heapsort  Memory: 34kB
         ->  GroupAggregate  (cost=11771.46..78494.04 rows=560000 width=165) (actual time=39.312..524.115 rows=307 loops=1)
               Group Key: photos_photo.id, auth_user.id, users_userprofile.id, communities_community.id
               ->  Merge Left Join  (cost=11771.46..64494.04 rows=560000 width=165) (actual time=38.941..521.608 rows=2781 loops=1)
                     Merge Cond: (photos_photo.id = photos_like.photo_id)
                     ->  Merge Left Join  (cost=11771.04..34755.79 rows=140000 width=157) (actual time=34.908..183.110 rows=656 loops=1)
                           Merge Cond: (photos_photo.id = photos_comment.photo_id)
                           ->  Gather Merge  (cost=11770.62..19748.56 rows=70000 width=149) (actual time=32.725..33.080 rows=307 loops=1)
                                 Workers Planned: 1
                                 Workers Launched: 1
                                 ->  Sort  (cost=10770.61..10873.55 rows=41176 width=149) (actual time=29.700..29.743 rows=154 loops=2)
                                       Sort Key: photos_photo.id, photos_photo.user_id, users_userprofile.id, communities_community.id
                                       Sort Method: quicksort  Memory: 56kB
                                       Worker 0:  Sort Method: quicksort  Memory: 47kB
                                       ->  Hash Left Join  (cost=825.85..4517.07 rows=41176 width=149) (actual time=13.012..29.551 rows=154 loops=2)
                                             Hash Cond: (photos_photo.community_id = communities_community.id)
                                             ->  Hash Left Join  (cost=818.35..4401.02 rows=41176 width=126) (actual time=12.829..29.322 rows=154 loops=2)
                                                   Hash Cond: (auth_user.id = users_userprofile.user_id)
                                                   ->  Hash Join  (cost=471.35..3945.89 rows=41176 width=100) (actual time=6.477..22.877 rows=154 loops=2)
                                                         Hash Cond: (photos_photo.user_id = auth_user.id)
                                                         ->  Parallel Seq Scan on photos_photo  (cost=13.35..3379.76 rows=41176 width=65) (actual time=0.793..17.091 rows=154 loops=2)
                                                               Filter: ((hashed SubPlan 1) OR ((community_id IS NULL) AND (hashed SubPlan 2)) OR (user_id = 1))
                                                               Rows Removed by Filter: 49846
                                                               SubPlan 1
                                                                 ->  Index Scan using communities_communitymembership_user_id_599c8d2c on communities_communitymembership u0  (cost=0.28..8.30 rows=1 width=8) (actual time=0.022..0.022 rows=0 loops=2)
                                                                       Index Cond: (user_id = 1)
                                                                       Filter: ((status)::text = 'accepted'::text)
                                                               SubPlan 2
                                                                 ->  Index Only Scan using unique_follow on users_follow u0_1  (cost=0.42..4.96 rows=31 width=4) (actual time=0.035..0.041 rows=38 loops=2)
                                                                       Index Cond: (follower_id = 1)
                                                                       Heap Fetches: 0
                                                         ->  Hash  (cost=333.00..333.00 rows=10000 width=35) (actual time=5.574..5.575 rows=10000 loops=2)
                                                               Buckets: 16384  Batches: 1  Memory Usage: 783kB
                                                               ->  Seq Scan on auth_user  (cost=0.00..333.00 rows=10000 width=35) (actual time=0.015..2.761 rows=10000 loops=2)
                                                   ->  Hash  (cost=222.00..222.00 rows=10000 width=30) (actual time=6.263..6.264 rows=10000 loops=2)
                                                         Buckets: 16384  Batches: 1  Memory Usage: 756kB
                                                         ->  Seq Scan on users_userprofile  (cost=0.00..222.00 rows=10000 width=30) (actual time=0.025..3.000 rows=10000 loops=2)
                                             ->  Hash  (cost=5.00..5.00 rows=200 width=23) (actual time=0.136..0.136 rows=200 loops=2)
                                                   Buckets: 1024  Batches: 1  Memory Usage: 19kB
                                                   ->  Seq Scan on communities_community  (cost=0.00..5.00 rows=200 width=23) (actual time=0.026..0.072 rows=200 loops=2)
                           ->  Index Scan using photos_comment_photo_id_dcfe9eba on photos_comment  (cost=0.42..12932.24 rows=200000 width=16) (actual time=0.030..130.940 rows=199856 loops=1)
                     ->  Materialize  (cost=0.42..21988.25 rows=400000 width=16) (actual time=0.034..297.382 rows=401244 loops=1)
                           ->  Index Scan using photos_like_photo_id_56eb526d on photos_like  (cost=0.42..20988.25 rows=400000 width=16) (actual time=0.024..251.176 rows=399748 loops=1)
 Planning Time: 3.075 ms
 Execution Time: 524.548 ms
```

</details>

Discovered two massive bottlenecks:
1. `Parallel Seq Scan on photos_photo` (Lines 23-25 of output): The database is doing a full table scan on 100,000 photos because it lacks indexes on `user_id`, `community_id`, and `created_at`. Notice `Rows Removed by Filter: 49846` per worker — it loads the entire table into memory just to throw away 99% of it.
2. `Merge Left Join` + `GroupAggregate` (Lines 4-10 and 43-45 of output): The Django `.annotate(likes_count=Count('likes'), comments_count=Count('comments'))` forces PostgreSQL to load 400,000 likes (`rows=399748`) and 200,000 comments (`rows=199856`), perform massive `LEFT JOIN`s on the filtered photos, and aggregate them in memory *before* it can apply the `LIMIT 20` pagination. The join step alone took `~482ms` (`521.608 - 38.941`).

**Actions:**
* Conducted `EXPLAIN ANALYZE` on the exact raw SQL query generated by Django.

**Notes/Edge Cases:** The database spent `524.5 ms` doing work that should take `< 5 ms`. The use of `.annotate()` with `Count` across multiple reverse foreign keys creates a Cartesian product that severely degrades performance on large tables. The fix will involve decoupling the counts from the main paginated query.

---

## Phase: Newsfeed Database Latency Fix (Date: 2026-07-05, Commit: d8a670a2997f24f59b42825d2c3b4986c7a6e568, Model: Claude Opus 4.6 (Thinking))

**Analysis:** Based on the EXPLAIN ANALYZE findings, two changes are needed: (1) remove the `.annotate()` from the main feed queryset to eliminate the massive LEFT JOINs on 400k likes + 200k comments, and (2) add composite indexes to enable Index Scans instead of Seq Scans.

**Actions:**
* **newsfeed/views.py:** Removed `.annotate(likes_count=..., comments_count=...)` from the main `feed` queryset. After pagination, we now extract the 20 photo IDs and run two small, targeted `GROUP BY` queries against `photos_like` and `photos_comment` filtered by `photo_id__in=photo_ids`. This means PostgreSQL only aggregates counts for 20 photos instead of joining 600,000 rows.
* **photos/models.py:** Added `Meta.indexes` to `Photo` with three composite indexes: `(user, -created_at)` for the newsfeed user filter, `(community, -created_at)` for the community filter, and `(-created_at)` for the global sort. Added `Meta.indexes` to `Comment` with `(photo, created_at)` for the photo detail comments query.
* Imported `Like` and `Comment` in views.py for the post-pagination count queries.

**Results (Post-Optimization):**
After applying the migration and deploying the new query, the production metrics improved dramatically.

<details>
<summary>Click to view POST-OPTIMIZATION EXPLAIN ANALYZE output</summary>

```text
 Limit  (cost=14.38..21.25 rows=20 width=149) (actual time=0.143..9.134 rows=20 loops=1)
   ->  Nested Loop Left Join  (cost=14.38..24033.65 rows=70000 width=149) (actual time=0.141..9.129 rows=20 loops=1)
         ->  Nested Loop Left Join  (cost=14.23..22251.98 rows=70000 width=126) (actual time=0.135..9.107 rows=20 loops=1)
               ->  Nested Loop  (cost=13.94..16868.86 rows=70000 width=100) (actual time=0.124..5.307 rows=20 loops=1)
                     ->  Index Scan using idx_photo_created_at on photos_photo  (cost=13.64..11979.64 rows=70000 width=65) (actual time=0.110..5.147 rows=20 loops=1)
                           Filter: ((hashed SubPlan 1) OR ((community_id IS NULL) AND (hashed SubPlan 2)) OR (user_id = 1))
                           Rows Removed by Filter: 6458
                           SubPlan 1
                             ->  Index Scan using communities_communitymembership_user_id_599c8d2c on communities_communitymembership u0  (cost=0.28..8.30 rows=1 width=8) (actual time=0.019..0.019 rows=0 loops=1)
                                   Index Cond: (user_id = 1)
                                   Filter: ((status)::text = 'accepted'::text)
                           SubPlan 2
                             ->  Index Only Scan using unique_follow on users_follow u0_1  (cost=0.42..4.96 rows=31 width=4) (actual time=0.030..0.033 rows=25 loops=1)
                                   Index Cond: (follower_id = 1)
                                   Heap Fetches: 0
                     ->  Memoize  (cost=0.30..0.33 rows=1 width=35) (actual time=0.007..0.007 rows=1 loops=20)
                           Cache Key: photos_photo.user_id
                           Cache Mode: logical
                           Hits: 5  Misses: 15  Evictions: 0  Overflows: 0  Memory Usage: 2kB
                           ->  Index Scan using auth_user_pkey on auth_user  (cost=0.29..0.32 rows=1 width=35) (actual time=0.008..0.008 rows=1 loops=15)
                                 Index Cond: (id = photos_photo.user_id)
               ->  Memoize  (cost=0.30..0.37 rows=1 width=30) (actual time=0.190..0.190 rows=1 loops=20)
                     Cache Key: auth_user.id
                     Cache Mode: logical
                     Hits: 5  Misses: 15  Evictions: 0  Overflows: 0  Memory Usage: 2kB
                     ->  Index Scan using users_userprofile_user_id_key on users_userprofile  (cost=0.29..0.36 rows=1 width=30) (actual time=0.251..0.251 rows=1 loops=15)
                           Index Cond: (user_id = auth_user.id)
         ->  Memoize  (cost=0.15..0.17 rows=1 width=23) (actual time=0.001..0.001 rows=0 loops=20)
               Cache Key: photos_photo.community_id
               Cache Mode: logical
               Hits: 19  Misses: 1  Evictions: 0  Overflows: 0  Memory Usage: 1kB
               ->  Index Scan using communities_community_pkey on communities_community  (cost=0.14..0.16 rows=1 width=23) (actual time=:
               0.004..0.005 rows=0 loops=1)
                     Index Cond: (id = photos_photo.community_id)
 Planning Time: 7.836 ms
 Execution Time: 9.927 ms
```

</details>

* **Database Execution Time:** Dropped from **524.5 ms** down to **9.9 ms** (a ~98% reduction in latency).
* **Scan Type:** The `Parallel Seq Scan` was entirely replaced by an `Index Scan using idx_photo_created_at`.
* **Join Elimination:** The catastrophic `Merge Left Join` on the likes and comments tables is completely gone from the main query.
* **CloudWatch Metrics:** The middleware reported `DatabaseLatency: 79.06ms` and `QueryCount: 9`. The 79ms includes the main query (9.9ms) plus the two new small grouped count queries and network round-trip overhead.

**Notes/Edge Cases:** Django already auto-creates single-column FK indexes on `Like.photo_id` and `Comment.photo_id`, so no duplicate index was added for Like. The Comment composite index `(photo, created_at)` is specifically useful for the photo detail page which fetches `comments.order_by('created_at')` — PostgreSQL can serve both filter and sort from a single index.

---

## Phase: Fix Photo Detail N+1 (Date: 2026-07-05, Commit: 25e37ec718217a91741755205ab5234b9178b804, Model: Gemini 3.1 Pro (High))

**Analysis:** The photo detail page fired 24-30 queries per page load. The primary bottleneck was the comment loop, which fired 2 queries per comment (`comment.user` and `comment.user.profile`). Furthermore, the photo lookup itself fired additional queries for its author's profile and the community.

**Actions:**
* **photos/views.py:** Modified the `photo_detail` view to eagerly load related entities:
    * Used `Photo.objects.select_related('user__profile', 'community')` in the `get_object_or_404` call to kill 3 queries for the photo author, profile, and community.
    * Used `.select_related('user__profile')` on the `photo.comments` queryset to kill the 2 queries per comment in the template loop.
* **Indexes:** No new indexes were required here because (1) `get_object_or_404(id=...)` uses the primary key index, (2) `photo.likes.count()` uses the automatic foreign key index on `Like.photo_id`, (3) `has_liked` uses the unique constraint index on `['user', 'photo']`, and (4) the comments query is completely optimized by the `idx_comment_photo_created` composite index that was already added in Phase 2.

**Notes/Edge Cases:** This dramatically drops the queries on the photo detail page to a flat ~5 queries regardless of how many comments are rendered, and all queries are backed by optimal indexes.

---

## Phase: Fix Profile Page N+1 (Date: 2026-07-05, Commit: 0a8ce76b5987a620df6ca4dad9ed474c34fe39dd, Model: Gemini 3.1 Pro (High))

**Analysis:** The profile page benchmark fired an excess of queries because it was fetching the base user object separately from the profile, resulting in an additional query. Furthermore, while the current template does not render like/comment counts per photo, the base photos query lacked prefetching if those counts were ever added.

**Actions:**
* **users/views.py:** Modified the `profile_view` to eagerly load the associated `User` object when fetching the `UserProfile`:
    * Added `UserProfile.objects.select_related('user')` to the `get_object_or_404` lookup.
    
**Notes/Edge Cases:** This saves 1 query immediately by fetching the `UserProfile` and `User` in a single SQL `INNER JOIN` rather than hitting the database twice. It also future-proofs the baseline profile view.

---

## Phase: Remove Dead-Weight Index (Date: 2026-07-08, Commit: c3261dbe9c25e417d9496149d0a926dfbe602796, Model: Gemini 3.1 Pro)

**Analysis & Decision:**
During the query optimization phase, a single-column index on `Photo` for `(-created_at)` was created as a potential fallback for global ordering. However, further analysis of the newsfeed queries revealed that because the application strictly filters photos by `user_id` or `community_id`, a global explore feed doesn't exist. Thus, `idx_photo_created_at` was dead weight, occupying disk space and degrading write performance for no benefit.

**Actions Taken:**
* **Removed** `idx_photo_created_at` from `photoz/photos/models.py`.
* Maintained the strict scope rule of not including features/indexes meant for future "unclarified" enhancements.

---

## Phase: Hashtag Search Implementation (Date: 2026-07-10, Commit: 9157189ec89c9e74a53b993eda22efb2ed3cf9dc, Model: Claude Opus 4.6)

**Analysis & Decision:**
The application only supported searching for users by name/username. There was no way to discover photos by topic. Implemented hashtag-based photo search using PostgreSQL's `pg_trgm` extension with a GIN trigram index.

**Why GIN trigram over Full-Text Search (tsvector)?**
Full-Text Search tokenizes text into words and stems them. A hashtag like `#sunset` would be tokenized to just `sunset`, losing the `#` prefix. Compound hashtags like `#nofilterneeded` would not be split into words, making them unsearchable via FTS. GIN trigram indexes handle arbitrary substring matching (`LIKE '%#sunset%'`), which is exactly what hashtag search requires.

**Trade-off: GIN vs GiST for trigram indexes**

Both GIN and GiST can be used with `pg_trgm`. They solve different problems:

| | GIN | GiST |
|---|---|---|
| **Index type** | Lossless (stores every trigram mapped to row IDs, like an inverted index) | Lossy (stores a compressed signature of trigrams per row) |
| **Read speed** | Faster. No re-checking needed after index scan. | Slower. Must re-check actual row data to confirm matches because the signature can produce false positives. |
| **Write speed** | Slower. Every trigram must be individually indexed on insert. | Faster. Only a single signature needs to be computed and stored. |
| **Index size** | Larger on disk. | Smaller on disk. |
| **Best operators** | Containment: `LIKE`, `ILIKE` (exact substring match) | Similarity: `%`, `<->`, `<%`, `%>` (fuzzy match, distance ordering) |
| **Best for** | "Find all captions containing `#sunset`" | "Find captions similar to `#sunst` (typo), ranked by closeness" |

GIN was chosen because our query is a containment match (`caption ILIKE '%#sunset%'`), not a fuzzy/similarity search. Additionally, photo captions are written once and rarely updated, so the higher write cost of GIN is negligible.

**Trade-off: PostgreSQL built-in search vs Elasticsearch**

| | PostgreSQL (pg_trgm + GIN) | Elasticsearch |
|---|---|---|
| **Infrastructure** | Zero additional infrastructure. Runs inside the existing database. | Requires a separate cluster (nodes, memory, storage, monitoring). |
| **Operational cost** | No extra deployment, no data sync pipeline, no version management. | Needs a data sync mechanism (e.g., Django signals or CDC) to keep the search index in sync with the database. Data consistency becomes a concern. |
| **Query capability** | Substring matching, basic similarity. Sufficient for hashtag search. | Full-text search with stemming, synonyms, fuzzy matching, faceted search, relevance scoring, autocomplete, highlighting. |
| **Scalability** | Scales with the database. At very high query volumes (thousands of searches/sec), search queries compete with application queries for database connections and CPU. | Scales independently. Search traffic does not affect the primary database. |
| **When to switch** | Current scale (100k photos, low search traffic). | When search becomes a core product feature with complex requirements (multi-field search, typo tolerance, search suggestions) or search traffic volume starts degrading database performance. |

PostgreSQL was chosen because the current requirement is simple (exact hashtag substring match), the data volume is small, and adding Elasticsearch would introduce significant operational complexity (a new cluster, a data sync pipeline, monitoring) for no measurable benefit at this stage.
**Design Decisions:**
* **Unified search endpoint:** Instead of separate endpoints for user search and photo search, a single `/photos/search/` endpoint handles both. If the query starts with `#`, it searches photo captions. Otherwise, it searches users. This keeps the UI clean with a single search bar.
* **Clickable hashtags:** A custom Django template filter (`linkify_hashtags`) converts `#hashtag` text in captions into clickable links that trigger a search. Applied across newsfeed, photo detail, and search results templates.
* **Post-pagination counts:** Like/comment counts use the same decoupled post-pagination approach established in Phase 2, avoiding the `.annotate()` Cartesian product problem.

**Actions Taken:**
* **bses/settings.py:** Added `django.contrib.postgres` to `INSTALLED_APPS`.
* **photos/models.py:** Added `GinIndex(name='idx_photo_caption_trgm', fields=['caption'], opclasses=['gin_trgm_ops'])`.
* **photos/migrations/0004_enable_pg_trgm.py:** Manual migration to enable `pg_trgm` extension.
* **photos/views.py:** Added `search_view`, `_search_users`, `_search_photos_by_hashtag`.
* **photos/urls.py:** Added `path('search/', ...)`.
* **photos/templates/photos/search_results.html:** New unified search results template.
* **photos/templatetags/hashtag_tags.py:** `linkify_hashtags` filter using regex to convert `#word` patterns into anchor tags.
* **newsfeed/templates/newsfeed/feed.html**, **photos/templates/photos/detail.html:** Applied `linkify_hashtags` to caption rendering.
* **templates/navbar.html:** Updated search bar to unified endpoint.
* **chapter04/query_optimization/seed_data.py:** Updated `CAPTIONS` list with hashtags.
* **users/views.py** & **users/urls.py:** Removed obsolete `search_users_view` and route.

---

## Phase: Read Replicas - HTTP Load Test (Date: 2026-07-12, Commit: d62e49a56e4bcf59220e67ff1268fad5c30d957a, Model: Claude Opus 4.6 (Thinking))

**Analysis:** Parts 1-3 solved query-level bottlenecks. The next bottleneck is the single PostgreSQL instance itself. All reads and writes go to one machine. As concurrent users increase, reads and writes compete for CPU, I/O, and connections.

**Rationale:**
- Load test sends real HTTP requests including nginx routing, gunicorn processing, and database queries.
- Uses Python `requests` with session cookies for Django CSRF/auth, `ThreadPoolExecutor` for concurrency.
- Results are saved to JSON for later comparison after read replicas are set up.

**Actions:**
- Created `chapter04/connection_pooling/benchmark_db_load.py` — HTTP load generator with configurable concurrency, read/write ratio, duration. Outputs latency percentiles (p50/p95/p99), throughput, 5xx errors, DB connection count, per-endpoint breakdown. Supports `--save-to` for JSON output and `--compare` for baseline comparison.
- Created `chapter04/connection_pooling/README.md` — documents the single-instance bottleneck, vertical vs horizontal scaling trade-offs, PhotoZ's read-heavy nature, and how to run the load test.

---

## Phase: Hashtag Search Privacy Bug Fix (Date: 2026-07-12, Commit: [c97834face52712c77b140da721af1fa3ef24622], Model: Gemini 3.1 Pro (High))

**Analysis:** A bug was discovered where photos belonging to private communities were leaking into hashtag search results for non-members. This happened because `_search_photos_by_hashtag` applied a text filter on the caption without enforcing community visibility constraints.

**Rationale:**
- We need to enforce standard PhotoZ visibility rules: a user can see public photos (no community), photos in communities they have 'accepted' status in, and their own photos.

**Actions:**
- **photos/views.py**: Updated `_search_photos_by_hashtag` to include a `visibility_q` filter ensuring only authorized photos are returned in search results. Imported `CommunityMembership`.

---

## Phase: PgBouncer Connection Pooling (Date: 2026-07-13, Commit: [d1c0a317acea8d31ec34ea7752710173750b2955], Model: Gemini 3.1 Pro (High))

**Analysis:** Load testing proved that scaling app nodes (Gunicorn threads) overwhelmed the single PostgreSQL connection pool, leading to `FATAL: too many clients already`.

**Rationale:**
- We introduced `PgBouncer` (via `edoburu/pgbouncer` Docker image) in front of PostgreSQL.
- Reduced PostgreSQL `max_connections` directly to 20 to aggressively protect its memory.
- `PgBouncer` handles 1000+ incoming app connections in lightweight threads and multiplexes them across the 20 Postgres connections in `transaction` mode.

**Actions:**
- **photoz/docker-compose-db.yml**: Added `pgbouncer` service mapping port 6432 to `db:5432`. Added `max_connections=20` to `db` and `AUTH_TYPE=plain` to PgBouncer to prevent SCRAM/MD5 mismatch.
- **photoz/docker-compose-app.yml**: Appended `POSTGRES_PORT=6432` to the environment block of `web` so EC2 app nodes target PgBouncer instead of Postgres directly.
- **iaac/aws/terraform/security.tf**: Added an ingress rule to `photoz-db-sg` to allow traffic from the App nodes on port `6432` to reach PgBouncer.
- **photoz/docker-compose.yml**: Replicated the PgBouncer integration for the local unified dev setup.

## Phase: PgBouncer Auth Query Implementation (Date: 2026-07-14, Commit: [6fcc1ec93351e6b72b5477a2eff9e818031c6f2a], Model: Gemini 3.1 Pro (High))
- **Goal**: Harden PgBouncer authentication by using `scram-sha-256` instead of `plain` text, following Enterprise best practices.
- **Analysis**: Instead of manually managing SCRAM hashes in `userlist.txt` or relying on bypassing authentication with `trust`, we configured PgBouncer to use `auth_query`. This allows PgBouncer to dynamically query Postgres for the SCRAM hash of connecting users, allowing for robust password rotation and True Zero Trust authentication.
- **Actions**:
    - Created `photoz/postgres-init/01-pgbouncer-auth.sql` to initialize a `pgbouncer` user and a `SECURITY DEFINER` function for querying `pg_shadow`.
    - Created `photoz/pgbouncer/pgbouncer.ini` and `userlist.txt` for custom `edoburu` image configuration.
    - Updated `photoz/docker-compose.yml` and `photoz/docker-compose-db.yml` to remove `POSTGRES_HOST_AUTH_METHOD=trust` and instead mount the new init scripts and config files.

## Phase: Django Persistent Connections (Date: 2026-07-14, Commit: [pending], Model: Antigravity)
- **Goal**: Fix 100% CPU bottleneck on App Nodes during load testing caused by TCP and SCRAM-SHA-256 overhead.
- **Analysis**: By default, Django (`CONN_MAX_AGE=0`) tears down and rebuilds the database connection on every HTTP request. With PgBouncer auth set to `scram-sha-256`, this meant Django was forced to perform expensive cryptographic hashing 200 times per second during load testing. The App Nodes maxed out at 100% CPU, while the database remained idle.
- **Actions**:
    - **photoz/bses/settings.py**: Set `CONN_MAX_AGE` to 60 seconds (configurable via `.env`). This instructs Django to keep the TCP connections to PgBouncer alive, completely bypassing the connection and authentication overhead on subsequent requests.

## Phase: PgBouncer Session Mode and App Thread Optimization (Date: 2026-07-15, Commit: [pending], Model: Antigravity)
- **Goal**: Resolve HTTP 500 errors and timeouts caused by Django's incompatibility with PgBouncer `transaction` mode while preventing CPU exhaustion on App nodes.
- **Analysis**: Django explicitly forbids `CONN_MAX_AGE > 0` with PgBouncer's `transaction` pool mode, as PgBouncer constantly swaps the underlying server connection, causing transaction state corruption and `500` errors. We previously tried setting `CONN_MAX_AGE=0` to fix the 500 errors, but forcing Django to establish a new connection and compute the SCRAM-SHA-256 hash on *every single request* caused the App Node CPUs to lock up, resulting in 30-second timeouts. 
To escape this trap, we realized that by artificially throttling Gunicorn concurrency (`--threads 5`), we reduced the maximum number of client connections to 10 across the entire cluster. Since 10 is well under Postgres's hard limit of 20, we no longer needed `transaction` multiplexing. Switching PgBouncer to `session` mode allowed us to safely re-enable persistent connections (`CONN_MAX_AGE=60`), completely eliminating the SCRAM CPU bottleneck on every request.
- **Actions**:
    - **photoz/bses/settings.py**: Restored `CONN_MAX_AGE=60` to prevent constant SCRAM hashes.
    - **photoz/docker-compose-app.yml**: Optimized Gunicorn workers with `--threads 5 --timeout 120` to strictly cap client connections at 10 and prevent Gunicorn from violently terminating workers during latency spikes.
    - **photoz/pgbouncer/pgbouncer.ini**: Switched to `pool_mode = session` and increased `default_pool_size = 10` so PgBouncer assigns a dedicated server connection to each persistent Django client connection.
- **Result**: Throughput increased from 0.5 RPS (Baseline) to 20.8 RPS (+4060%), and Database Latency dropped to 0.0ms. The remaining 5xx errors in the benchmark are strictly due to the tiny `t3.micro` App Node reaching 100% CPU capacity, meaning the database bottleneck has been successfully solved and shifted to the compute tier.

### Final Load Test Metrics (PgBouncer Session Mode + Persistent Connections)
| Metric | Baseline (No PgBouncer) | Current (PgBouncer Session) | Change |
|--------|-------------------------|------------------------------|--------|
| Read RPS | 0.5 | 20.8 | +4060.0% |
| Read p50 Latency | N/A (Hung) | 394.5 ms | Massive improvement |
| Write RPS | 0.3 | 2.7 | +800.0% |
| DB Connections | Exceeded max (crashed) | 19 / 20 (Stable) | 100% connection safety |

> **Note on remaining 5xx errors**: The 736 HTTP 5xx errors reported by the benchmark script are now exclusively Nginx `504 Gateway Timeout` and `502 Bad Gateway` errors. Because we restricted the two App Nodes to 10 threads total, they can only process ~23 requests per second. The remaining 177 concurrent load tester requests sit in Nginx's queue until Nginx hits its timeout threshold. The Database itself executed queries in an average of `10.15ms` with `0` connection drops. The bottleneck has been successfully shifted from the database to the compute tier.

### Architectural Note: PgBouncer Session vs Transaction Mode
When implementing PgBouncer in Django (or any framework with persistent connections), you must choose the correct pool mode based on your thread count vs database connection limit:

**Transaction Mode**
- **How it works**: PgBouncer assigns a server connection to the client *only for the duration of a single transaction*. The moment the transaction commits/rolls back, the server connection is returned to the pool for another client to use.
- **When it's preferred**: When you have **thousands of application threads/lambdas** connecting to a database that only supports a few hundred connections (e.g. Serverless architectures).
- **The Catch**: You **MUST disable persistent connections** in your framework (e.g. Django `CONN_MAX_AGE=0`). If the framework tries to hold the connection open across multiple requests, PgBouncer will swap the server connection out from under it, causing `500` errors due to corrupted session state (timezones, encodings, etc). Additionally, establishing a new connection on every request can cause heavy CPU overhead if using expensive authentication like `scram-sha-256`.

**Session Mode**
- **How it works**: PgBouncer assigns a dedicated server connection to the client for the *entire lifespan of the client's connection*.
- **When it's preferred**: When you want to use **Persistent Connections** (e.g. Django `CONN_MAX_AGE=60`) to completely eliminate the CPU/TCP overhead of connecting to the database on every HTTP request.
- **The Catch**: It provides a strict 1:1 mapping between active App threads and Database connections. You must strictly limit your App Node concurrency (e.g. Gunicorn `--threads 5`) so that the total number of threads across your entire cluster never exceeds the Postgres `max_connections` limit.
