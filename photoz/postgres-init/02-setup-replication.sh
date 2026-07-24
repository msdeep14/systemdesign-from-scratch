#!/bin/bash
set -e

echo ">>> Configuring Primary Node for Replication..."

# Configure postgresql.conf for streaming replication and query statistics
cat >> ${PGDATA}/postgresql.conf <<EOF
wal_level = replica
max_wal_senders = 10
max_replication_slots = 10
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all
EOF

# Create a dedicated replication user
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER replicator WITH REPLICATION ENCRYPTED PASSWORD 'replicator_password';
EOSQL

# Allow the replication user to connect from any IP (in the docker network)
echo "host replication replicator all md5" >> ${PGDATA}/pg_hba.conf

echo ">>> Primary Node configured."
