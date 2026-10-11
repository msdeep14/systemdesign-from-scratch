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

## Phase 2: Topics & Consumer Execution

1. **Install Python Kafka Dependencies:**
   Activate your virtual environment and install `confluent-kafka`:
   ```bash
   cd photoz
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Provision Topics from Settings (Idempotent):**
   Run the setup script. It reads `KAFKA_TOPICS` from `bses/settings.py` and creates any missing topics and DLQs:
   ```bash
   cd photoz
   python kafka_setup.py
   ```

3. **Verify Created Topics & Partitions:**
   List all topics on the Kafka broker:
   ```bash
   docker exec -it photoz-kafka-1 /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
   ```
   Inspect a topic's 50-partition layout:
   ```bash
   docker exec -it photoz-kafka-1 /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic photo.events.likes
   ```

4. **Run the Consumer Daemons:**
   - In terminal 1, run the likes consumer daemon:
     ```bash
     cd photoz
     python manage.py run_kafka_consumers
     ```
   - In terminal 2, run the followers consumer daemon:
     ```bash
     cd photoz
     python manage.py run_followers_consumer
     ```

5. **Test Consumer Event Processing via Console Producer:**
   *Note: PostgreSQL enforces Foreign Key constraints on `Like` (must reference existing `Photo` and `User`) and `Follow` (must reference existing `User`s). Ensure test records exist before sending events:*

   - **Step 5a: Ensure test records exist in PostgreSQL:**
     ```bash
     cd photoz
     python manage.py shell -c "
from django.contrib.auth.models import User
from photos.models import Photo
u1, _ = User.objects.get_or_create(username='alice')
u2, _ = User.objects.get_or_create(username='bob')
p1, _ = Photo.objects.get_or_create(user=u1, defaults={'caption': 'Test Photo'})
print(f'Test User 1 ID: {u1.id}, Test User 2 ID: {u2.id}, Test Photo ID: {p1.id}')
"
     ```

   - **Step 5b: Send a test Like event:**
   Replace the user id and photo id from above command.
     ```bash
     docker exec -i photoz-kafka-1 /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic photo.events.likes <<< '{"photo_id": 1, "user_id": 1}'
     ```
     *Expected in `run_kafka_consumers` output:*
     ```text
     Bulk inserted 1 likes into PostgreSQL.
     ```

   - **Step 5c: Send a test Follow event:**
     ```bash
     docker exec -i photoz-kafka-1 /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic photo.events.follows <<< '{"follower_id": 1, "following_id": 2}'
     ```
     *Expected in `run_followers_consumer` output:*
     ```text
     Bulk inserted 1 follows with updated follower counts.
     ```
