#!/bin/bash
set -e

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo ">>> Primary data not found in replica. Starting pg_basebackup..."
  
  # Wait for primary to be ready
  export PGPASSWORD=replicator_password
  until pg_isready -h ${PRIMARY_DB_HOST:-db} -p 5432 -U replicator -d postgres; do
    echo "Waiting for primary database to become ready..."
    sleep 2
  done

  # Perform base backup
  # -D: output directory
  # -U: replication user
  # -vP: verbose and progress
  # -R: creates postgresql.auto.conf and standby.signal for replication
  # -X stream: streams WAL files while backup is taken
  pg_basebackup -h ${PRIMARY_DB_HOST:-db} -p 5432 -D ${PGDATA} -U replicator -vP -R -X stream -C -S ${REPLICA_SLOT_NAME:-replica_1}
  
  echo ">>> pg_basebackup complete. Starting replica..."
fi

# Hand over control to the default postgres entrypoint
# The standard entrypoint will skip initdb because PG_VERSION exists now
exec docker-entrypoint.sh "$@"
