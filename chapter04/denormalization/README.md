# Denormalization: Likes and Comments Count

This section benchmarks the cost of computing `likes_count` and `comments_count` at read time (via SQL `COUNT` queries), then eliminates those queries by adding counter columns directly to the `photos_photo` table.

The migration uses a **two-stage deploy** so users never see incorrect counts during the rollout.

---

## Baseline Benchmark Results (Before Denormalization)

Collected on AWS deployment with 100,000 photos, 400,000 likes, 200,000 comments. Concurrency = 20 simultaneous requests.

| Scenario | Avg | p50 | p95 | Max |
|---|---|---|---|---|
| Newsfeed page load | 633ms | 606ms | 1303ms | 1303ms |
| Profile page | 344ms | 269ms | 1168ms | 1168ms |
| Photo detail | 268ms | 204ms | 1137ms | 1137ms |

The p95 spike (1–2 seconds) is caused by COUNT queries on the `Like` and `Comment` tables contending under concurrent load. p50 is acceptable because individual COUNT queries are fast — the problem is contention when many requests hit the same tables simultaneously.

---

## Two-Stage Deploy

### Stage 1: Schema migration (safe to run on live traffic)

Stage 1 adds the columns and backfills them from existing data. The application code is **not changed** — it still reads from COUNT queries. Users see no change in behavior.

**Step 1: Pull the latest code on the app node**

```bash
ssh -i <your_key.pem> ubuntu@<APP_EC2_PUBLIC_IP>
cd systemdesign-from-scratch
git pull origin main
```

**Step 2: Run migration 0006 — ADD COLUMN only**

The app runs in Docker. Use `docker compose exec` to run inside the running `web` container.

Django migrations must bypass PgBouncer — PgBouncer's transaction pooling mode does not support the DDL statements Django issues. Connect directly to Postgres instead.

Find the actual Postgres host:

```bash
cd photoz
docker compose exec web env | grep POSTGRES
```

Run the migration (replace `<DB_HOST>` with the value from above):

```bash
docker compose exec -e POSTGRES_HOST=<DB_HOST> -e POSTGRES_PORT=5432 web python manage.py migrate photos 0006
```

This only runs `ALTER TABLE ADD COLUMN` — it commits in under 1 second with no table rewrite.

The migration has `lock_timeout = 2s`. If there is an active transaction holding the table when you run it, the migration fails immediately with `canceling statement due to lock timeout`. This is correct behavior — no traffic was blocked. Just retry the command until it prints `OK`.

**Step 3: Run migration 0007 — backfill existing data**

```bash
docker compose exec -e POSTGRES_HOST=<DB_HOST> -e POSTGRES_PORT=5432 web python manage.py migrate photos 0007
```

This reads all Photo rows and writes the correct `likes_count` and `comments_count` from the `Like` and `Comment` tables. It commits every 500 rows independently, so it does not hold a long-running transaction. Estimated time: 60–90 seconds for 100,000 photos.

**Step 4: Verify the backfill**

```bash
docker compose exec web python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bses.settings')
django.setup()
from photos.models import Photo
p = Photo.objects.first()
print('Column likes_count:', p.likes_count, '| Real count:', p.likes.count())
p2 = Photo.objects.order_by('-likes_count').first()
print('Most liked photo:', p2.id, '| Column:', p2.likes_count, '| Real:', p2.likes.count())
"
```

Both lines should show matching numbers. If they match, Stage 1 is complete.

---

### Stage 2: Code switch (deploys the actual optimization)

Stage 2 updates the application code to read from the new columns and maintain them via atomic `F()` increments on write. This is a separate deploy done only after Stage 1 is verified.

**Step 1: Deploy code changes to the app nodes**

```bash
ssh -i <your_key.pem> ubuntu@<APP_EC2_PUBLIC_IP>
cd systemdesign-from-scratch
git pull origin main
cd photoz
docker compose restart web
```

(Repeat on all app nodes)

**Step 2: Benchmark Results (After Denormalization)**

Once deployed, the `COUNT(*)` queries are eliminated from the hot paths.

| Scenario | Original p95 | New p95 | Improvement |
|---|---|---|---|
| Newsfeed page load | ~1303ms | **610ms** | ~53% faster |
| Profile page | ~1168ms | **312ms** | ~73% faster |
| Photo detail | ~1137ms | **673ms** | ~40% faster |

The massive reduction in p50/p95 latency is due to the elimination of the complex `Merge Left Join` and `GroupAggregate` SQL operations that PostgreSQL was previously forced to perform on every page load. The read path is now fully optimized and counts are strictly maintained via atomic `F()` increments during write actions.

---

## Troubleshooting: Killing a Stuck Migration Session

If a migration was cancelled mid-run (e.g. killed with Ctrl+C, or timed out), the Postgres transaction may not have rolled back yet. The open transaction holds a lock on `photos_photo`, blocking all subsequent DDL.

Symptoms: every retry of the migration immediately fails with `canceling statement due to lock timeout`.

**Option A: From the app node (via docker exec into the web container)**

```bash
docker compose exec -e POSTGRES_HOST=<DB_HOST> -e POSTGRES_PORT=5432 web python -c "
import psycopg2
conn = psycopg2.connect(host='<DB_HOST>', port=5432, dbname='bses', user='postgres', password='postgres')
conn.autocommit = True
cur = conn.cursor()

# Show all long-running queries (older than 30 seconds)
cur.execute('''
    SELECT pid, now() - query_start AS duration, state, query
    FROM pg_stat_activity
    WHERE state != 'idle'
      AND query_start < now() - interval '30 seconds'
    ORDER BY duration DESC;
''')
for row in cur.fetchall():
    print(row)
"
```

Once you identify the stuck PID, terminate it:

```bash
docker compose exec -e POSTGRES_HOST=<DB_HOST> -e POSTGRES_PORT=5432 web python -c "
import psycopg2
conn = psycopg2.connect(host='<DB_HOST>', port=5432, dbname='bses', user='postgres', password='postgres')
conn.autocommit = True
cur = conn.cursor()

# Terminate all long-running transactions touching photos_photo
cur.execute('''
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE state != 'idle'
      AND query_start < now() - interval '30 seconds'
      AND query LIKE '%photos_photo%';
''')
print('Terminated:', cur.fetchall())
"
```

**Option B: From the DB node directly**

```bash
ssh -i <key.pem> ubuntu@<DB_EC2_PUBLIC_IP>
docker compose exec db psql -U postgres -d bses
```

Then inside psql:

```sql
-- Find the stuck session
SELECT pid, now() - query_start AS duration, state, left(query, 100)
FROM pg_stat_activity
WHERE state != 'idle'
  AND query_start < now() - interval '30 seconds'
ORDER BY duration DESC;

-- Terminate it by PID
SELECT pg_terminate_backend(<pid>);
```

After termination, retry migration 0006. The `lock_timeout = 2s` ensures the retry is safe — it either succeeds quickly or fails fast without blocking traffic.

---


## Running the Benchmarks

### Before benchmark (HTTP, against AWS)

Run from your local machine with the venv activated:

```bash
python chapter04/denormalization/benchmark_before_http.py \
    --url http://<LB_PUBLIC_IP> \
    --username <test_user> \
    --password <password> \
    --iterations 20 \
    --concurrency 20
```

### After benchmark (HTTP, against AWS)

Run after Stage 2 is deployed:

```bash
python chapter04/denormalization/benchmark_after_http.py \
    --url http://<LB_PUBLIC_IP> \
    --username <test_user> \
    --password <password> \
    --iterations 20 \
    --concurrency 20
```

### Local DB benchmark (ORM-level, for raw query cost)

Useful for understanding query-level impact independent of caching and network:

```bash
# Requires: local Postgres running with seeded data (see chapter04/query_optimization/seed_data.py)
python chapter04/denormalization/benchmark_before.py
```
