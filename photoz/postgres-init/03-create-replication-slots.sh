#!/bin/bash
set -e

# Creates one physical replication slot per replica on the primary PostgreSQL node.
#
# This script is called by Terraform after the primary DB restarts with
# wal_level=replica active. It can also be run manually on the primary EC2
# instance if you need to re-create slots without re-running Terraform.
#
# Usage:
#   REPLICA_COUNT=2 ./postgres-init/03-create-replication-slots.sh
#   REPLICA_COUNT=1 ./postgres-init/03-create-replication-slots.sh

if [ -z "$REPLICA_COUNT" ]; then
  echo "WARNING: REPLICA_COUNT environment variable is not set. Skipping replication slot creation."
  exit 0
fi

if [ "$REPLICA_COUNT" -eq 0 ]; then
  echo "REPLICA_COUNT is 0. Skipping replication slot creation."
  exit 0
fi

echo ">>> Creating $REPLICA_COUNT replication slot(s)..."

for i in $(seq 1 $REPLICA_COUNT); do
  SLOT_NAME="replica_${i}"
  echo "  Creating slot: $SLOT_NAME"
  docker exec photoz-db-1 psql -U postgres -c "SELECT pg_create_physical_replication_slot('$SLOT_NAME');"
done

echo ">>> Done. Verify with:"
echo "    docker exec photoz-db-1 psql -U postgres -c \"SELECT slot_name, active FROM pg_replication_slots;\""
