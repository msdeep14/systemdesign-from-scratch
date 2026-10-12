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

## Phase 6: Celery Decommissioning (Part 1: Workflow Migration)

In Phase 6, all remaining Celery-dependent background tasks are migrated to Kafka topics and consumers, removing all Celery tasks and beat schedules from the application codebase.

### 1. Migrated Workflows Overview

| Workflow | Old Celery Task / Beat | New Kafka Topic | New Consumer Daemon |
| :--- | :--- | :--- | :--- |
| **Notifications** | `send_*_notification_task` | `photo.events.notifications` | `python manage.py run_notifications_consumer` |
| **Photo Deletions** | `fanout_photo_deleted_task` | `photo.events.deletions` | `python manage.py run_deletions_consumer` |
| **Like Count Sync** | `flush_like_counts_task` (Beat) | `photo.events.likes` | Handled atomically in `run_kafka_consumers` |
| **Follow Count Sync** | `flush_follower_counts_task` (Beat) | `photo.events.follows` | Handled atomically in `run_followers_consumer` |

### 2. Notifications Consumer Daemon

1. **Run the Consumer:**
   ```bash
   cd photoz
   python manage.py run_notifications_consumer
   ```
2. **Topic**: `photo.events.notifications` (Consumer Group: `photoz-notifications-group`)
3. **Payload Examples:**
   - Photo activity:
     ```json
     {"event_type": "photo_activity", "photo_id": 1, "actor_id": 2, "notif_type": "photo_like", "verb": "liked"}
     ```
   - Community invitation:
     ```json
     {"event_type": "member_invited", "community_id": 5, "target_user_id": 3, "inviter_id": 2, "membership_id": 10}
     ```
   - User tagged:
     ```json
     {"event_type": "tagged", "object_id": 1, "tagged_user_id": 3, "tagger_id": 2, "object_type": "photo"}
     ```

### 3. Deletions Consumer Daemon

1. **Run the Consumer:**
   ```bash
   cd photoz
   python manage.py run_deletions_consumer
   ```
2. **Topic**: `photo.events.deletions` (Consumer Group: `photoz-deletions-group`)
3. **Payload Example:**
   ```json
   {"user_id": 1, "photo_id": 10}
   ```
4. **Behavior**: The consumer pulls deletion events and invalidates the cached newsfeeds of all active followers in Redis.

### 4. Infrastructure & Dependency Cleanup (Part 2)

Following workflow migration to Kafka, Celery infrastructure and dependencies have been decommissioned:
- **Local Compose (`photoz/docker-compose.yml`)**: Removed `celery`, `celery-beat`, and `flower` services.
- **Production Compose (`photoz/docker-compose-app.yml`)**: Removed `celery` and `celery-beat` services.
- **Python Dependencies (`photoz/requirements.txt`)**: Removed `celery`, `celery-redbeat`, and `flower`. Retained `redis>=5.0.1` for newsfeed caching and distributed locks.
- **Terraform Security Groups (`iaac/aws/terraform/security.tf`)**: Removed ingress rules permitting the Redis node to connect to PostgreSQL (5432) and PgBouncer (6432) for Celery Beat.

---

## Phase 7: AWS Infrastructure Deployment (Terraform & KRaft EC2)

In Phase 7, the Apache Kafka cluster is provisioned on AWS EC2 using Terraform in KRaft mode, isolating the Control Plane from the Data Plane across 3 Availability Zones.

### 1. Cluster Architecture

| Tier | Role | Count | Instance Type | Storage | Network / AZ | Ports |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Control Plane** | `controller` | 3 | `t3.medium` | Root EBS (gp3) | 3 Subnets across 3 AZs | `9093` (Quorum) |
| **Data Plane** | `broker` | 3 | `t3.medium` | 50GB gp3 EBS per broker | 3 Subnets across 3 AZs | `9092` (PLAINTEXT) |

- **No Zookeeper**: Uses modern KRaft consensus metadata quorum (`KAFKA_PROCESS_ROLES=controller`).
- **Data Isolation**: Commit logs are written to dedicated attached gp3 EBS volumes (`/dev/xvdf` mounted at `/var/lib/kafka/data`).
- **Fault Tolerance**: Distributed across 3 Availability Zones with `--replication-factor 3` and `min.insync.replicas 2`.
- **Security**: Port `9093` is restricted to internal controller quorum. Port `9092` is accessible only to App nodes and brokers within the VPC. No Kafka ports are publicly exposed.

### 2. Terraform Resources

- **`network.tf`**: Provisions 3 public subnets across 3 distinct Availability Zones (`ap-south-1a`, `ap-south-1b`, `ap-south-1c`).
- **`security.tf`**: Defines `photoz-kafka-controller-sg` and `photoz-kafka-broker-sg`.
- **`kafka.tf`**:
  - `aws_instance.kafka_controller[3]`: Controllers with IDs `1, 2, 3` and predictable private IPs `10.0.0.20`, `10.0.1.20`, `10.0.2.20`.
  - `aws_instance.kafka_broker[3]`: Brokers with IDs `101, 102, 103` and predictable private IPs `10.0.0.30`, `10.0.1.30`, `10.0.2.30`.
  - `aws_ebs_volume.kafka_broker_data[3]` & `aws_volume_attachment.kafka_broker_data[3]`: 50GB gp3 EBS volumes.
- **`main.tf`**: Injects `KAFKA_BOOTSTRAP_SERVERS` into App node `.env` templates.
- **`outputs.tf`**: Exports `kafka_controller_private_ips`, `kafka_broker_private_ips`, and `kafka_bootstrap_servers`.

### 3. Deploying and Verifying on AWS

1. **Plan & Apply Infrastructure:**
   ```bash
   cd iaac/aws/terraform
   terraform init
   terraform plan
   terraform apply
   ```

2. **Verify Broker Connectivity from App Nodes:**
   ```bash
   # SSH into any App node
   nc -zv 10.0.0.30 9092
   nc -zv 10.0.1.30 9092
   nc -zv 10.0.2.30 9092
   ```

3. **Verify Topics and Cluster Metadata:**
   ```bash
   # Run topic setup against the cluster
   docker exec -it photoz-web-1 python kafka_setup.py
   ```
