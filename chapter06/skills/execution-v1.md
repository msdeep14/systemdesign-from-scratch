# Chapter 6 Execution Log - v1

## Phase: Celebrity Users & Fan-Out Bottleneck (Date: 2026-09-13, Commit: 2e4f672b275548d6625ca406a59f285308799ca9, Model: Gemini 3.1 Pro (High), planning with Claude Sonnet 4.6 Thinking)
*   **Analysis**: To demonstrate the bottleneck in synchronous fan-out of photo uploads to followers' feeds, we needed to simulate high-load conditions by seeding celebrity users with a large number of followers.
*   **Actions**:
    *   Created `photoz/users/management/commands/seed_celebrity_users.py` to bulk create base users and follow relationships for 3 celebrities: `@celeb_500k`, `@celeb_1m`, and `@celeb_2m`. The script sets up the users with the password `password123`.
    *   Created benchmarking script `chapter06/benchmarks/upload_timing.py` using `requests` module to simulate a login and a multipart image upload (generating a dummy image in memory) to measure end-to-end response times and timeout behaviors.
    *   Created `chapter06/README.md` to document the setup steps.
*   **Benchmark results**: `celeb_500k` upload took 30.24s; `celeb_1m` and `celeb_2m` returned 504 (Gunicorn timeout). Root cause: `newsfeed/signals.py` pushed to all follower Redis feeds synchronously in the HTTP thread.

## Phase: Hybrid Push/Pull Fan-Out Fix (Date: 2026-09-14, Commit: 3296471544ed79d7370ec304c3cdb02f16e01097, Model: Claude Sonnet 4.6 Thinking)
*   **Analysis**: Pure async Pub/Sub moves the 2M Redis writes off the HTTP thread but does not reduce the total write volume. The Hybrid Push/Pull approach eliminates celebrity fan-out entirely at write time and merges their photos at read time instead. This is the same strategy used by Instagram and Twitter.
*   **Decision**: Denormalize `follower_count` on `UserProfile` (indexed). Checked at upload time via `photo.user.profile.follower_count`. Above 10,000 threshold = celebrity, skip fan-out. At feed read time, query celebrity photos directly from DB and merge with the Redis-cached regular feed.
*   **Actions**:
    *   Added `follower_count = PositiveIntegerField(default=0, db_index=True)` to `UserProfile` model and generated migration `users/migrations/0003_userprofile_follower_count.py`.
    *   Created `users/signals.py` with `post_save`/`post_delete` handlers on `Follow` to atomically increment/decrement `follower_count` using `F()` expressions.
    *   Wired `users/signals.py` in `UsersConfig.ready()` in `users/apps.py`.
    *   Added `get_celebrity_followed_ids(user_id, threshold)` to `users/services.py`.
    *   Created `users/management/commands/backfill_follower_counts.py` to sync counts from the `Follow` table for existing rows (needed because `bulk_create` in seeding bypasses signals).
    *   Updated `newsfeed/signals.py`: celebrities skip fan-out; regular users keep push-on-write.
    *   Updated `newsfeed/services.py`: added `CELEBRITY_FOLLOWER_THRESHOLD`, `get_celebrity_user_ids()` (Redis-cached per user, 5min TTL), and merged celebrity photo pull into `get_cached_feed()`.
    *   Added `get_celebrity_photo_ids(celebrity_user_ids, limit)` to `photos/services.py`.
*   **Edge case**: `bulk_update` requires objects fetched from the DB (with PK set), not in-memory constructed instances. Fixed the backfill command accordingly.
*   **Note**: Only 25,004 `UserProfile` rows exist (3 celebrities + ~25,001 signup users). The 2M seeded follower accounts are bare `auth_user` rows with no profile — they're synthetic accounts and will never upload photos. The backfill correctly skips them.

## Phase: Replicate Follower Count Hot Row Problem (Date: 2026-09-26, Commit: 5e6750e1ad27da279000689f8def475ca1fc457e, Model: Gemini 3.1 Pro High)
*   **Analysis**: The `F("follower_count") + 1` operation in `users/signals.py` causes a synchronous row-level lock in PostgreSQL on `UserProfile`. We wrote HTTP benchmarking scripts to hit the `/users/<celeb>/follow/` endpoint concurrently to replicate this bottleneck.
*   **Actions**:
    *   Created `chapter06/benchmarks/follow_timing.py` to simulate N users concurrently clicking "Follow". Discovered that pulling CSRF tokens inline inside the concurrent block flooded the Gunicorn queue, creating a false benchmark reading. Factored the GET requests out to the setup phase to isolate the POST latency.
    *   Created `chapter06/benchmarks/compare_hot_row.py` to definitively prove the DB lock limits throughput by comparing a "Scattered Load" (hitting different rows) against a "Concentrated Load" (hitting a single row). 
    *   Identified the **Connection Funnel**: Our Docker setup strictly limits traffic to 10 max concurrent DB connections. At this scale, the DB resolves locks in <1ms, so the system never bottlenecks on the database row lock locally, only at the web server limit (~1,000 RPS).

## Phase: Fix Search Logout Bug (Date: 2026-09-26, Commit: f010727ad9b70d3c7cb5b7faadba09a68a438d17, Model: Gemini 3.1 Pro)
*   **Analysis**: URL path collision caused users to be logged out when searching for certain names (e.g. "logout").
*   **Actions**:
    *   Modified `logout_view` in `users/views.py` to enforce `@require_POST`.
    *   Added reserved username validation to `UserRegistrationForm`.

* Phase: Implement Celery/Redis for Follower Counts (Date: 2026-09-26, Commit: pending, Model: Antigravity)
    * Updated Terraform `iaac/aws/terraform/main.tf` and `docker-compose-app.yml` to provision Celery worker on app node ASG.
    * Updated Terraform `main.tf` to provision `docker-compose-redis.yml` (Celery Beat) on the Redis singleton node.
    * Added Django application logic (`users/services.py`, `tasks.py`, `celery.py`) for asynchronous follower count flush via Redis `INCR` to eliminate PostgreSQL hot row locking.

## Phase: Likes Hot Row Replication (Date: 2026-09-29, Commit: 70e390a5d3745db767cb1a2b9828b6b5890bfa12, Model: Claude Sonnet 4.6 Thinking)
*   **Analysis**: Replicated the row-level lock contention for `photos_photo.likes_count`. Every like fires `UPDATE photos_photo SET likes_count = likes_count + 1 WHERE id = ?`, which acquires an exclusive row lock. Under high concurrency all requests serialize behind that lock. Local tests masked this because Django HTTP overhead (~200ms) dwarfs the ~0.1ms lock wait. The effect is only visible on AWS where PgBouncer connection pool (pool_size=20) and network latency (3-5ms per DB hop) compound with the lock queue.
*   **Actions**:
    *   Created `chapter06/benchmarks/benchmark_likes_hot_row.py` — N concurrent users all like the same celebrity photo (one burst, same pattern as `compare_hot_row.py`). Script signs up sessions, fires all likes simultaneously, reports total time, throughput, avg/p95/p99/min/max latency.
    *   Fixed `users/management/commands/backfill_follower_counts.py` — original command loaded all 3.5M users into one dict and issued a single huge `IN (...)` query, killing the DB connection. Rewrote to use `.iterator(chunk_size=5000)` and compute follower counts per batch to avoid memory spike and connection timeouts.
    *   Updated `chapter06/README.md` with new benchmark instructions.
    *   **Fix Implementation**: Implemented the "Full Count" Redis strategy for likes to completely bypass the database hot row on write.
        *   Added `get_photo_likes_count` and `update_like_count_redis` in `photos/services.py` to maintain the absolute like count in Redis and a set of pending updates.
        *   Updated `toggle_like` and `photo_detail` in `photos/views.py` to read/write from Redis instead of hitting PostgreSQL directly.
        *   Created `flush_like_counts_task` in `photos/tasks.py` and scheduled it in `bses/settings.py` via Celery Beat to flush counts to PostgreSQL every 10 seconds.
*   **Benchmark results on AWS (3000 concurrency)**:
    *   300 users: 0.75s total, 401 req/s, p99=716ms — lock drains fast at low concurrency.
    *   3000 users: 75.22s total, 30 req/s, p99=4839ms, 723 failures — lock queue grows faster than it drains. `pg_stat_activity` showed `max_connections` fully exhausted (`sorry, too many clients already`) during the run — both row-lock serialization and connection pool saturation confirmed.
*   **Edge case**: `backfill_follower_counts` ran successfully on AWS manual invocation but crashed mid-way (PgBouncer connection drop) during cloud-init because the old implementation loaded all 3.5M user IDs into memory at once. The celebrity profiles happened to be in an early batch that committed before the crash. The batched rewrite eliminates this.

## Phase: Object Caching & Thundering Herd Prevention (Date: 2026-09-30, Commit: d91784756300a10df02f629a17e1224065d22260, Model: Gemini 3.1 Prod)
*   **Analysis**: While the "Full Count" strategy fixed the write bottleneck for likes, celebrity photos still face a massive read bottleneck. If a celebrity photo isn't cached (or expires), a "Thundering Herd" of concurrent feed requests could crash the database with identical `SELECT * FROM photos_photo WHERE id = ?` queries.
*   **Actions**:
    *   Implemented full `Photo` object caching in Redis (`photo:{id}:data`) via `_serialize_photo()`.
    *   Created `get_cached_photo` in `photos/services.py` implementing a Cache Promise (Mutex Lock) using `SETNX`.
    *   Solved the Thundering Herd waiting mechanism by leveraging **Redis Pub/Sub (Push) instead of polling**: the thread acquiring the lock fetches from the DB, populates the cache, and calls `PUBLISH channel:photo:{id}:populated READY`. Waiting threads efficiently block via `pubsub.subscribe()` and `get_message()` until notified.
    *   Centralized TTL constants in `bses/settings.py` (`CACHE_TTL_CELEBRITY_PHOTO` = 24h, `CACHE_TTL_NORMAL_PHOTO` = 1h, `CELEBRITY_FOLLOWER_THRESHOLD` = 10000) to apply a hybrid lazy-loading vs. proactive caching strategy depending on the uploader's follower count.


## Phase: Prove Celery Fanout Bottleneck (Worker Starvation) (Date: 2026-10-02, Commit: 907e6a7f1f687b3523286f2fac3dbb6c799714e0, Model: Gemini 3.1 Pro)
*   **Analysis**: To demonstrate why a naive Celery loop over 10,000 followers causes "Worker Starvation", we needed a script that bypassed the slow HTTP login layer to inject 10k users directly into the DB, and then test multiple concurrent photo uploads to saturate the worker pool.
*   **Actions**:
    *   Created `chapter06/benchmarks/benchmark_celery_fanout.py` which seeds N "Power Users" (each with 9,999 followers) into the database in under a second using `bulk_create`.
    *   Iterated on the script to properly fix DB injection rules (Postgres Foreign Key constraints) and properly handle the "Cache Warming" (the celery worker ignores cold caches).
    *   Updated the script with `--concurrency` utilizing `concurrent.futures.ThreadPoolExecutor` to perform concurrent photo uploads.
    *   Updated `chapter06/README.md` with instructions on how to test this end-to-end via AWS and an explanation of the results (4 uploads took 8s, 15 uploads took 39s).

## Phase: Step 1 Fix - Redis Pipelining (Date: 2026-10-02, Commit: Pending, Model: Gemini 3.1 Pro)
*   **Analysis**: The Celery fan-out loop was performing thousands of independent TCP requests to Redis. By wrapping the loop in a `redis_client.pipeline()`, we batch these commands into a single round-trip, drastically reducing the network latency bottleneck.
*   **Actions**:
    *   Created `push_to_feed_cache_bulk` in `photoz/newsfeed/services.py`. It uses a 2-phase pipeline strategy: phase 1 batches `EXISTS` checks, and phase 2 batches `LPUSH` and `LTRIM` operations only on the existing caches to prevent creating partial cold feeds.
    *   Updated `fanout_photo_uploaded_task` in `photoz/newsfeed/tasks.py` to fetch `follower_ids` and pass them to the bulk pipeline function.

