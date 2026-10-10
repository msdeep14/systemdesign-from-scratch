# Kafka Local Development & Verification

This document tracks how to run, verify, and test the local Kafka cluster during our migration away from RabbitMQ/Celery. It will be updated progressively as we add Topics, Consumers, and Producers.

## Phase 1: Local Kafka Setup

To verify that the local Kafka KRaft broker is running correctly alongside the rest of the Photoz stack:

1. **Start the cluster:**
   Navigate to the `photoz` directory and spin up the Kafka container in the background:
   ```bash
   cd photoz
   docker compose up -d kafka
   ```

2. **Verify Broker Health:**
   Check the logs to ensure the KRaft controller and broker booted successfully without Zookeeper:
   ```bash
   docker compose logs kafka
   ```
   *You should see logs indicating the Kafka Server started and the KRaft Quorum is established.*

3. **Verify Internal Connectivity:**
   You can exec into the container and use the built-in Kafka bash scripts to list available topics (it should return empty right now):
   ```bash
   docker exec -it photoz-kafka-1 /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
   ```

4. **Verify KRaft Quorum and Broker Status:**
   You can inspect the health of the KRaft Controller and the state of the Brokers directly using the metadata quorum tool:
   ```bash
   docker exec -it photoz-kafka-1 /opt/kafka/bin/kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --status
   ```
   To see a detailed breakdown of all voters (Controllers) and observers (Brokers) in the cluster:
   ```bash
   docker exec -it photoz-kafka-1 /opt/kafka/bin/kafka-metadata-quorum.sh --bootstrap-server localhost:9092 describe --replication
   ```
