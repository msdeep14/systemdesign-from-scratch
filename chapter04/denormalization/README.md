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
cd systemdesignfromscratch
git pull origin main
```

**Step 2: Run the migration**

```bash
cd photoz
source venv/bin/activate
python manage.py migrate photos 0006
```

The migration runs two operations:
1. `ALTER TABLE photos_photo ADD COLUMN likes_count integer DEFAULT 0 NOT NULL` — fast, no table rewrite on Postgres.
2. `ALTER TABLE photos_photo ADD COLUMN comments_count integer DEFAULT 0 NOT NULL` — same.
3. `RunPython` backfill — reads all Photo rows in batches of 500 and writes the correct counts from the `Like` and `Comment` tables.

Estimated time: 30–90 seconds depending on DB load and number of photos.

**Step 3: Verify the backfill**

```bash
python -c "
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

Stage 2 is not yet implemented. It will be added here once Phases 4 and 5 are complete.

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
