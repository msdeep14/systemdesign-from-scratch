#!/bin/bash
set -e

echo ">>> Configuring Primary Node for Replication..."

# Configure postgresql.conf for streaming replication
cat >> ${PGDATA}/postgresql.conf <<EOF
wal_level = replica
max_wal_senders = 10
max_replication_slots = 10
EOF

# Create the replication user
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER replicator WITH REPLICATION ENCRYPTED PASSWORD 'replicator_password';
EOSQL

# Pre-create one replication slot per replica.
# Slots are created here so they exist before pg_basebackup runs on each replica.
# This prevents the crash loop caused by pg_basebackup failing mid-run and leaving
# a stale slot that blocks all subsequent retries.
REPLICA_COUNT=${REPLICA_COUNT:-1}
for i in $(seq 1 $REPLICA_COUNT); do
  SLOT_NAME="replica_${i}"
  echo ">>> Creating replication slot: $SLOT_NAME"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "SELECT pg_create_physical_replication_slot('$SLOT_NAME');"
done

# Allow the replication user to connect from any IP (in the docker network)
echo "host replication replicator all md5" >> ${PGDATA}/pg_hba.conf

echo ">>> Primary Node configured."
