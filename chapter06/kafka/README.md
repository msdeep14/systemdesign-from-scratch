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

## Phase 3: Producer Integration & Web Flow Verification

In Phase 3, Kafka event producers are integrated into the Django web request flows via `bses.kafka.publish_kafka_event`. This replaces synchronous database writes and Celery tasks for write-heavy interactions.

1. **Integrated Web Endpoints:**
   - **Like a Photo (`photos/views.py:toggle_like`)**: Emits to `photo.events.likes` partitioned by `photo_id`.
   - **Follow a User (`users/views.py:toggle_follow_view`)**: Emits to `photo.events.follows` partitioned by `target_user.id`.
   - **Upload a Photo (`photos/views.py:upload_photo`)**: Emits to `photo.events.uploads` partitioned by `user.id`.

2. **Verify End-to-End Producer Flow via Django Shell:**
   ```bash
   cd photoz
   python manage.py shell -c "
   from bses.kafka import publish_kafka_event, get_kafka_producer
   # Publish like event using valid user and photo IDs
   publish_kafka_event('likes', {'photo_id': 395305, 'user_id': 70004}, key='395305')
   # Publish follow event
   publish_kafka_event('follows', {'follower_id': 70004, 'following_id': 70008}, key='70008')
   get_kafka_producer().flush()
   print('Events published successfully.')
   "
   ```

3. **Verify Consumer Output:**
   In the active consumer terminal (`python manage.py run_kafka_consumers` or `python manage.py run_followers_consumer`), you will see:
   ```text
   Successfully processed 1 records.
   ```
   *Note: If an event contains an invalid foreign key (e.g. from manual test injection), the consumer logs the integrity error, skips the poison pill, and commits the offset so legitimate messages continue processing.*

## Phase 4: Newsfeed Fan-out Consumer & Celery Decommissioning

In Phase 4, the legacy Celery asynchronous fanout mechanism (`fanout_photo_uploaded_task`) is decommissioned and replaced by a dedicated Kafka uploads consumer (`run_uploads_consumer`).

1. **Run the Uploads Consumer Daemon:**
   - In a new terminal, run the uploads consumer:
     ```bash
     cd photoz
     python manage.py run_uploads_consumer
     ```
   - The consumer listens on topic `photo.events.uploads` using consumer group `photoz-uploads-group`.

2. **Photo Upload Message Format:**
   - **Topic**: `photo.events.uploads`
   - **Partition Key**: String representation of `user_id` (e.g. `"1"`), ensuring per-user upload events preserve ordering.
   - **Payload JSON Schema**:
     ```json
     {
       "photo_id": 1,
       "user_id": 1
     }
     ```
   - **Field Specifications**:
     - `photo_id` (integer, required): ID of the uploaded photo.
     - `user_id` (integer, required): ID of the user who uploaded the photo.
   - *Note*: If either `photo_id` or `user_id` is missing or invalid, the consumer routes the payload to `photo.events.uploads.dlq`.

3. **Publish and Test Photo Upload Event Manually:**
   - **Via Kafka Console Producer (with Partition Key):**
     ```bash
     docker exec -i photoz-kafka-1 /opt/kafka/bin/kafka-console-producer.sh \
       --bootstrap-server localhost:9092 \
       --topic photo.events.uploads \
       --property "parse.key=true" \
       --property "key.separator=:" <<< '1:{"user_id": 1, "photo_id": 1}'
     ```
   - **Via Kafka Console Producer (without Key):**
     ```bash
     docker exec -i photoz-kafka-1 /opt/kafka/bin/kafka-console-producer.sh \
       --bootstrap-server localhost:9092 \
       --topic photo.events.uploads <<< '{"user_id": 1, "photo_id": 1}'
     ```
   - **Via Django Shell:**
     ```bash
     cd photoz
     python manage.py shell -c "
     from bses.kafka import publish_kafka_event, get_kafka_producer
     publish_kafka_event('uploads', {'user_id': 1, 'photo_id': 1}, key='1')
     get_kafka_producer().flush()
     print('Upload event emitted.')
     "
     ```

4. **Verify Fanout Behavior:**
   - The consumer pulls upload events and delegates to `bulk_fanout_photo_uploads`.
   - The photo is pushed to the uploader's Redis newsfeed cache.
   - If the uploader is not a celebrity (`follower_count <= 25,000`), the photo is pushed in pipelined batches of 1,000 to all active followers' feed caches.
   - Expected consumer output:
     ```text
     Successfully processed 1 records.
     ```

## Phase 5: Dead Letter Queue (DLQ) & Retry Policy

Phase 5 introduces exponential backoff retries for transient database errors and automatic Dead Letter Queue (DLQ) routing for corrupted messages and poison pills across all Kafka consumers.

### Architectural Mechanism

1. **Exponential Backoff for Transient Failures**:
   - Consumers retry database write failures up to 3 times (`max_retries = 3`).
   - Backoff starts at 0.5s and doubles on each retry attempt (`0.5s`, `1.0s`, `2.0s`).

2. **Poison Pill Isolation**:
   - If a batch insertion fails due to an `IntegrityError` (e.g., foreign key violations), the consumer falls back to single-record persistence.
   - Valid records in the batch are saved to the database.
   - The invalid record is packaged into a diagnostic envelope and routed to `{topic}.dlq`.
   - Primary partition offsets are committed, preventing consumer stalls and deadlocks.

3. **Malformed & Deserialization Errors**:
   - Non-JSON bytes or payloads with missing schema keys are automatically routed to the corresponding `.dlq` topic.

### Testing and Inspecting Dead Letter Queues

1. **Inject a Corrupted Record (Non-JSON String):**
   ```bash
   docker exec -i photoz-kafka-1 /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic photo.events.likes <<< 'corrupted-payload'
   ```

2. **Inject a Foreign Key Poison Pill:**
   ```bash
   docker exec -i photoz-kafka-1 /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic photo.events.likes <<< '{"photo_id": 999999999, "user_id": 999999999}'
   ```

3. **Inspect Dead Letter Queue Topics:**
   ```bash
   # Inspect likes DLQ
   docker exec -i photoz-kafka-1 /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic photo.events.likes.dlq --from-beginning --max-messages 5

   # Inspect follows DLQ
   docker exec -i photoz-kafka-1 /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic photo.events.follows.dlq --from-beginning --max-messages 5

   # Inspect uploads DLQ
   docker exec -i photoz-kafka-1 /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic photo.events.uploads.dlq --from-beginning --max-messages 5
   ```

4. **DLQ Message Structure:**
   Each message in a DLQ topic contains a diagnostic envelope:
   ```json
   {
     "original_topic": "photo.events.likes",
     "original_payload": {"photo_id": 999999999, "user_id": 999999999},
     "error_type": "IntegrityError",
     "error_message": "insert or update on table \"photos_like\" violates foreign key constraint...",
     "timestamp": 1791730425.24,
     "retry_count": 0
   }
   ```
   For failed photo uploads routed to `photo.events.uploads.dlq` (e.g. malformed schema):
   ```json
   {
     "original_topic": "photo.events.uploads",
     "original_payload": {"photo_id": 10},
     "error_type": "DeserializationError",
     "error_message": "Missing required keys 'user_id' or 'photo_id'",
     "timestamp": 1791730450.12,
     "retry_count": 0
   }
   ```




