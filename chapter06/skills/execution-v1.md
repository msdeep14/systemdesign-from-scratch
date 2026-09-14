# Chapter 6 Execution Log - v1

## Phase: Celebrity Users & Fan-Out Bottleneck (Date: 2026-09-13, Commit: 2e4f672b275548d6625ca406a59f285308799ca9, Model: Gemini 3.1 Pro (High), planning with Claude Sonnet 4.6 Thinking)
*   **Analysis**: To demonstrate the bottleneck in synchronous fan-out of photo uploads to followers' feeds, we needed to simulate high-load conditions by seeding celebrity users with a large number of followers.
*   **Actions**:
    *   Created `photoz/users/management/commands/seed_celebrity_users.py` to bulk create base users and follow relationships for 3 celebrities: `@celeb_500k`, `@celeb_1m`, and `@celeb_2m`. The script sets up the users with the password `password123`.
    *   Created benchmarking script `chapter06/benchmarks/upload_timing.py` using `requests` module to simulate a login and a multipart image upload (generating a dummy image in memory) to measure end-to-end response times and timeout behaviors.
    *   Created `chapter06/README.md` to document the setup steps.
*   **Benchmark results**: `celeb_500k` upload took 30.24s; `celeb_1m` and `celeb_2m` returned 504 (Gunicorn timeout). Root cause: `newsfeed/signals.py` pushed to all follower Redis feeds synchronously in the HTTP thread.

## Phase: Hybrid Push/Pull Fan-Out Fix (Date: 2026-09-14, Commit: pending, Model: Claude Sonnet 4.6 Thinking)
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
