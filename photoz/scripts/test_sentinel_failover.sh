#!/bin/bash
set -e

echo "=== Verifying Sentinel Cluster Status ==="
SENTINEL_MASTERS=$(docker exec photoz-sentinel-1 redis-cli -p 26379 sentinel masters)
echo "$SENTINEL_MASTERS" | grep -E "name|ip|num-slaves"

echo "=== Scaling to 4th Read Replica ==="
# To dynamically add more read replicas:
# 1. Spin up new container pointing to current primary
# 2. Sentinel auto-discovers newly joined replicas
echo "Starting redis-replica-4..."
docker rm -f photoz-redis-replica-4 2>/dev/null || true
docker run -d --name photoz-redis-replica-4 --network photoz_default redis:7 redis-server --replicaof redis-primary 6379 --protected-mode no

sleep 3
NUM_SLAVES=$(docker exec photoz-sentinel-1 redis-cli -p 26379 sentinel master mymaster | grep -A 1 "num-slaves" | tail -n 1)
echo "Updated replica count discovered by Sentinel: $NUM_SLAVES"

echo "=== Testing Sentinel Automated Failover ==="
echo "Pausing primary instance to trigger failover..."
docker pause photoz-redis-primary
sleep 6

NEW_MASTER_IP=$(docker exec photoz-sentinel-1 redis-cli -p 26379 sentinel get-master-addr-by-name mymaster | head -n 1)
echo "New elected master IP: $NEW_MASTER_IP"

echo "Unpausing previous primary..."
docker unpause photoz-redis-primary
sleep 2

docker stop photoz-redis-replica-4 && docker rm photoz-redis-replica-4
echo "=== Sentinel Failover Verification Complete ==="
