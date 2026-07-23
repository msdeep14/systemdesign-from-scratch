# Read Your Writes Consistency

## The Problem

In a primary-replica database setup, writes go to the primary and reads are randomly distributed (for Photoz architecture) across replicas. PostgreSQL streaming replication is **asynchronous** by default, meaning there is a small delay (typically milliseconds, but it can spike under load) before a write on the primary is made visible to replicas.

This creates a specific consistency violation called **"Read Your Writes"**: a user performs an action (e.g., posts a comment), the page reloads, and their comment is missing because the read was served by a replica that hasn't received the write yet.

## The Test

`test_ryw_consistency.py` automates this exact scenario. It:

1. Logs in as `test_user`
2. Posts a comment with a unique ID (UUID) to a photo
3. Immediately reads the photo detail page
4. Checks if the UUID appears in the HTML response
5. Repeats N times and reports how many reads returned stale data

### Running the test

Because PostgreSQL streaming replication on a local machine is typically sub-millisecond, it is too fast to catch with a Python script. To simulate the network latency and disk I/O load of a production environment, you must artificially delay the replica locally:

```bash
# From the photoz/ directory, inject a 1-second replication delay:
# For same commands on cloud deployment, replace the replica name with photoz-db-replica-1
docker compose exec db-replica psql -U postgres -c "ALTER SYSTEM SET recovery_min_apply_delay = '1s';"
docker compose exec db-replica psql -U postgres -c "SELECT pg_reload_conf();"
```

Now you can run the test script and observe the failures:

```bash
# From the root directory:
python chapter04/read_your_writes/test_ryw_consistency.py --url http://localhost --iterations 10
```

**Important: Reverting the Delay**
After testing the fix, you must revert the replica back to real-time replication, or it will permanently lag behind the primary by 1 second, causing issues with other tests:

```bash
# From the photoz/ directory:
docker compose exec db-replica psql -U postgres -c "ALTER SYSTEM SET recovery_min_apply_delay = '0';"
docker compose exec db-replica psql -U postgres -c "SELECT pg_reload_conf();"
```

### Expected output (after fix)

After implementing the Read Your Writes middleware, all reads should return `OK` because the middleware forces post-write reads to the primary database.

## The Fix

The fix uses a **cookie-based routing** approach:

1. A middleware detects when a user performs a write (`POST`, `PUT`, `PATCH`, `DELETE`).
2. It sets a short-lived cookie (`force_primary=true`, TTL=5 seconds) on the response.
3. On subsequent requests, the database router checks for this cookie. If present, it routes the read to the primary instead of a replica.
4. After 5 seconds (enough time for replication to catch up), the cookie expires and reads resume going to replicas.

This is a targeted approach: only the user who just wrote gets their reads pinned to the primary, and only for a few seconds. All other users continue reading from replicas normally.
