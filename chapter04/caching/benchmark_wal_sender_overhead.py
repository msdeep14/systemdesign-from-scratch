#!/usr/bin/env python3
"""
Benchmark: WAL Sender Overhead When Scaling Read Replicas.

This script proves that adding more read replicas increases load on the
primary database -- specifically the WAL (Write-Ahead Log) sender overhead.

What this script does:
    1. Snapshots pg_stat_replication BEFORE the write workload.
    2. Runs a write-heavy workload (bulk INSERTs directly into the DB).
    3. Continuously polls pg_stat_replication every second DURING writes.
    4. Snapshots AFTER the workload completes.
    5. Reports: walsender count, WAL bytes sent per replica, max replication lag.

Usage:

    # Terminal 1: Open the tunnel to the primary DB
    # ssh -i key.pem -N -L 5432:127.0.0.1:5432 ubuntu@<db-public-ip>

    # Terminal 2: Run the script
    python chapter04/caching/benchmark_wal_sender_overhead.py \
        --db-host 127.0.0.1 \
        --db-password <password> \
        --writes 50000
"""

import argparse
import os
import sys
import threading
import time

import psycopg2
from psycopg2.extras import execute_values


def connect(host, port, dbname, user, password):
    return psycopg2.connect(
        host=host, port=port, dbname=dbname, user=user, password=password,
        connect_timeout=10,
    )


def get_walsender_count(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'walsender';"
        )
        return cur.fetchone()[0]


def get_replication_stats(conn):
    """
    Returns one row per replica: application_name, write_lag, flush_lag,
    replay_lag (as microseconds), and WAL bytes in flight.
    sent_lsn - write_lsn = bytes the replica has received but not yet written to disk.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                application_name,
                state,
                pg_wal_lsn_diff(sent_lsn, write_lsn)   AS bytes_in_flight,
                EXTRACT(EPOCH FROM write_lag)  * 1000   AS write_lag_ms,
                EXTRACT(EPOCH FROM flush_lag)  * 1000   AS flush_lag_ms,
                EXTRACT(EPOCH FROM replay_lag) * 1000   AS replay_lag_ms,
                pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS unsent_bytes
            FROM pg_stat_replication
            ORDER BY application_name;
        """)
        return cur.fetchall()


def get_total_wal_generated(conn):
    """Returns total WAL bytes generated since server start (pg_current_wal_lsn offset)."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0');")
        return cur.fetchone()[0]


def run_write_workload(host, port, dbname, user, password, n_writes, results):
    """
    Performs n_writes bulk INSERTs into a temporary benchmark table.
    Runs in a background thread so we can poll pg_stat_replication concurrently.
    Uses a dedicated connection separate from the monitoring connection.
    """
    conn = connect(host, port, dbname, user, password)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS _wal_benchmark_tmp (
                    id SERIAL PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                );
            """)
        conn.commit()

        batch_size = 1000
        total_written = 0
        start = time.time()

        while total_written < n_writes:
            batch = min(batch_size, n_writes - total_written)
            rows = [(f"benchmark-payload-{total_written + j}",) for j in range(batch)]
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    "INSERT INTO _wal_benchmark_tmp (payload) VALUES %s",
                    rows,
                )
            conn.commit()
            total_written += batch

        elapsed = time.time() - start
        results["writes_done"] = total_written
        results["write_duration_s"] = elapsed
        results["writes_per_sec"] = total_written / elapsed

        # Cleanup
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS _wal_benchmark_tmp;")
        conn.commit()
    finally:
        conn.close()


def poll_replication_during_writes(conn, poll_interval, results, stop_event):
    """
    Polls pg_stat_replication every poll_interval seconds until stop_event is set.
    Tracks peak lag and maximum bytes in flight across all replicas.
    """
    peak_write_lag_ms = 0.0
    peak_replay_lag_ms = 0.0
    peak_bytes_in_flight = 0
    samples = []

    while not stop_event.is_set():
        rows = get_replication_stats(conn)
        for row in rows:
            _, _, bytes_in_flight, write_lag_ms, flush_lag_ms, replay_lag_ms, unsent = row
            bytes_in_flight = bytes_in_flight or 0
            write_lag_ms = write_lag_ms or 0.0
            replay_lag_ms = replay_lag_ms or 0.0
            peak_write_lag_ms = max(peak_write_lag_ms, write_lag_ms)
            peak_replay_lag_ms = max(peak_replay_lag_ms, replay_lag_ms)
            peak_bytes_in_flight = max(peak_bytes_in_flight, bytes_in_flight)
        samples.append(rows)
        time.sleep(poll_interval)

    results["peak_write_lag_ms"] = peak_write_lag_ms
    results["peak_replay_lag_ms"] = peak_replay_lag_ms
    results["peak_bytes_in_flight"] = peak_bytes_in_flight
    results["samples"] = samples


def print_separator(char="-", width=100):
    print(char * width)


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark WAL sender overhead when scaling read replicas"
    )
    parser.add_argument("--db-host", required=True,
                        help="Primary DB host (private IP on AWS)")
    parser.add_argument("--db-port", type=int, default=5432,
                        help="Primary DB port (default: 5432)")
    parser.add_argument("--db-name", default=os.environ.get("POSTGRES_DB", "bses"),
                        help="DB name (default: bses or POSTGRES_DB env var)")
    parser.add_argument("--db-user", default=os.environ.get("POSTGRES_USER", "postgres"),
                        help="DB user (default: postgres or POSTGRES_USER env var)")
    parser.add_argument("--db-password", default=os.environ.get("POSTGRES_PASSWORD", "postgres"),
                        help="DB password (default: postgres or POSTGRES_PASSWORD env var)")
    parser.add_argument("--writes", type=int, default=50000,
                        help="Number of rows to INSERT during the workload (default: 50000)")
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="Seconds between pg_stat_replication polls (default: 1.0)")
    args = parser.parse_args()

    print("\n" + "=" * 100)
    print("  BENCHMARK: WAL Sender Overhead on Primary (Replica Scaling Cost)")
    print("=" * 100)
    print(f"  Primary DB: {args.db_host}:{args.db_port}/{args.db_name}")
    print(f"  Write workload: {args.writes:,} INSERTs")
    print()

    monitor_conn = connect(args.db_host, args.db_port, args.db_name, args.db_user, args.db_password)

    # Snapshot before workload
    walsender_count = get_walsender_count(monitor_conn)
    wal_before = get_total_wal_generated(monitor_conn)
    replicas_before = get_replication_stats(monitor_conn)

    print(f"  Walsender processes on primary: {walsender_count}")
    print(f"  Connected replicas: {len(replicas_before)}")
    print()

    if not replicas_before:
        print("  WARNING: No replicas connected. Run with at least db_replica_count=1.")
        print("           This benchmark only makes sense with replicas attached.")

    print("  Replica state before workload:")
    print_separator()
    if replicas_before:
        print(f"  {'Replica':<20} {'State':<15} {'Write lag (ms)':<18} {'Replay lag (ms)':<18} {'Bytes in flight'}")
        print_separator()
        for row in replicas_before:
            name, state, bif, write_lag, flush_lag, replay_lag, unsent = row
            print(f"  {name:<20} {state:<15} {(write_lag or 0):<18.2f} {(replay_lag or 0):<18.2f} {(bif or 0):,}")
    else:
        print("  (no replicas)")
    print()

    print(f"  Starting write workload ({args.writes:,} INSERTs)...")
    print_separator()

    write_results = {}
    poll_results = {}
    stop_event = threading.Event()

    # Run write workload in background thread
    write_thread = threading.Thread(
        target=run_write_workload,
        args=(args.db_host, args.db_port, args.db_name, args.db_user, args.db_password,
              args.writes, write_results),
        daemon=True,
    )

    # Run pg_stat_replication poller in background thread
    poll_thread = threading.Thread(
        target=poll_replication_during_writes,
        args=(monitor_conn, args.poll_interval, poll_results, stop_event),
        daemon=True,
    )

    write_thread.start()
    poll_thread.start()
    write_thread.join()
    stop_event.set()
    poll_thread.join()

    wal_after = get_total_wal_generated(monitor_conn)
    replicas_after = get_replication_stats(monitor_conn)
    wal_generated_mb = (wal_after - wal_before) / (1024 * 1024)

    monitor_conn.close()

    print(f"\n  Write workload done:")
    print(f"    Rows inserted:   {write_results.get('writes_done', 0):,}")
    print(f"    Duration:        {write_results.get('write_duration_s', 0):.1f}s")
    print(f"    Throughput:      {write_results.get('writes_per_sec', 0):.0f} rows/sec")
    print(f"    WAL generated:   {wal_generated_mb:.2f} MB")

    print("\n" + "=" * 100)
    print("  RESULTS: pg_stat_replication (DURING & AFTER workload)")
    print("=" * 100)

    print(f"\n  Peak replication lag DURING write workload:")
    print(f"    Peak write_lag:         {poll_results.get('peak_write_lag_ms', 0):.2f} ms")
    print(f"    Peak replay_lag:        {poll_results.get('peak_replay_lag_ms', 0):.2f} ms")
    print(f"    Peak bytes in flight:   {poll_results.get('peak_bytes_in_flight', 0):,} bytes")

    print(f"\n  Replica state AFTER workload:")
    print_separator()
    if replicas_after:
        print(f"  {'Replica':<20} {'State':<15} {'Write lag (ms)':<18} {'Replay lag (ms)':<18} {'Bytes in flight'}")
        print_separator()
        for row in replicas_after:
            name, state, bif, write_lag, flush_lag, replay_lag, unsent = row
            print(f"  {name:<20} {state:<15} {(write_lag or 0):<18.2f} {(replay_lag or 0):<18.2f} {(bif or 0):,}")
    else:
        print("  (no replicas)")

    replica_count = len(replicas_after) if replicas_after else walsender_count

    print("\n" + "=" * 100)
    print("  INTERPRETATION")
    print("=" * 100)
    print(f"""
  Primary ran {walsender_count} walsender process(es) for {replica_count} replica(s).
  The primary generated {wal_generated_mb:.2f} MB of WAL for {write_results.get('writes_done', 0):,} writes.

  With {replica_count} replica(s), the primary streamed approximately:
    {wal_generated_mb:.2f} MB x {replica_count} replica(s) = {wal_generated_mb * replica_count:.2f} MB total outbound WAL
""")


if __name__ == "__main__":
    main()
