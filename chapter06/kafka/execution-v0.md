
## Phase: Local Kafka Setup (Date: 2026-10-10, Commit: 02a185909e1b07c9830c2c692e07645b2e6d6b0d, Model: Gemini 3.1 Pro High)
*   **Rationale**: Adding Kafka to the local development environment using Bitnami Kafka KRaft to begin testing local Kafka Producer/Consumer logic before AWS deployment.
*   **Actions**:
    *   Updated `photoz/docker-compose.yml` to include a new `kafka` service using `apache/kafka:4.3.1` in KRaft mode.
    *   Added `kafka_data` docker volume.

## Phase: Phase 2: Kafka Consumers and Topic Setup (Date: 2026-10-11, Commit: 74341f9, Model: Gemini 3.1 Pro High)
*   **Rationale**: Implementing Python consumers and initializing KRaft topics to transition off RabbitMQ/Celery.
*   **Actions**:
    *   Added confluent-kafka to photoz/requirements.txt.
    *   Added KAFKA_BOOTSTRAP_SERVERS and KAFKA_TOPICS registry to photoz/bses/settings.py.
    *   Updated photoz/kafka_setup.py to be config-driven and idempotent by comparing cluster metadata against settings.
    *   Created photoz/photos/management/commands/run_kafka_consumers.py to batch consume likes and bulk insert into PostgreSQL.
    *   Created photoz/users/management/commands/run_followers_consumer.py to pull Follow events, bulk insert relationships, and atomically update UserProfile.follower_count using F() expressions in a single transaction.
    *   Updated both consumers to read topic configurations dynamically from Django settings.
    *   Created `photoz/bses/kafka_consumer.py` with `BaseKafkaConsumerCommand` to encapsulate connection, polling, batching, deserialization, and offset commit lifecycle, eliminating code duplication across consumer commands.
    *   Added `bulk_record_follows` to `photoz/users/services.py` and `bulk_record_likes` to `photoz/photos/services.py`.
    *   Refactored consumer commands into minimal handlers (<10 lines each) inheriting from `BaseKafkaConsumerCommand` and delegating DB writes to domain services, eliminating drift's mutant duplicate and coupling findings.
    *   Refactored `kafka_setup.py` to reduce local variables, catch `KafkaException`, and add type annotations/docstrings.
    *   Updated chapter06/kafka/README.md with execution and verification commands.

## Phase: Phase 3: Kafka Producers Implementation (Date: 2026-10-11, Commit: 7f71777b4eacbf552a3b73db4429fa0acc7c0b17, Model: Gemini 3.1 Pro High)
*   **Rationale**: Transitioning synchronous write operations for likes, follows, and photo uploads into asynchronous Kafka event publishing, removing synchronous database bottlenecks from request/response cycles.
*   **Actions**:
    *   Created `photoz/bses/kafka.py` consolidating `publish_kafka_event`, `get_kafka_producer`, and `BaseKafkaConsumerCommand` to maintain architectural cohesion and avoid package-level pattern fragmentation.
    *   Integrated `publish_kafka_event` into `upload_photo` (`"uploads"`) and `toggle_like` (`"likes"`) in `photoz/photos/views.py`.
    *   Integrated `publish_kafka_event` into `toggle_follow_view` (`"follows"`) in `photoz/users/views.py`.
    *   Updated `run_kafka_consumers.py` and `run_followers_consumer.py` to import `BaseKafkaConsumerCommand` from `bses.kafka`.
    *   Removed redundant standalone files `photoz/bses/kafka_consumer.py` and `photoz/bses/kafka_producer.py`.
    *   Added `IntegrityError` fallback in `BaseKafkaConsumerCommand` to log and bypass poison pill records with invalid foreign keys so consumer loops do not deadlock.
    *   Configured Kafka dual listeners in `photoz/docker-compose.yml` (`kafka:29092` for Docker internal services, `localhost:9092` for host) and passed `KAFKA_BOOTSTRAP_SERVERS=kafka:29092` to `web` and `celery` containers to resolve connection refused errors from web UI.
    *   Verified all 6 pre-commit hooks (`ruff`, `ruff-format`, `pylint`, `import-linter`, `drift-check`, `calm-validate`) pass cleanly with exit code 0.

## Phase: Phase 4: Newsfeed Fan-out Consumer & Celery Decommissioning (Date: 2026-10-11, Commit: c9359f6, Model: Gemini 3.1 Pro High)
*   **Rationale**: Transition newsfeed fanout from legacy Celery worker tasks to a dedicated Kafka upload consumer (`run_uploads_consumer`), decoupling photo uploads from Celery message queues and providing bounded backpressure.
*   **Actions**:
    *   Created `photoz/newsfeed/management/commands/run_uploads_consumer.py` subclassing `BaseKafkaConsumerCommand` to consume `photo.events.uploads` in batches of 100.
    *   Added `get_user_follower_count` and `get_follower_ids_by_user_id` to `photoz/users/services.py` for follower lookups.
    *   Added `bulk_fanout_photo_uploads` to `photoz/newsfeed/services.py` with batch chunking (1,000) and celebrity threshold checks (`CELEBRITY_FOLLOWER_THRESHOLD = 25,000`).
    *   Removed `fanout_photo_uploaded_task` and `fanout_photo_uploaded_chunk_task` from `photoz/newsfeed/tasks.py`.
    *   Removed `photo_uploaded` signal handler `_handle_photo_uploaded` from `photoz/newsfeed/signals.py` and decoupled `upload_photo` in `photoz/photos/views.py`.
    *   Standardized error handling blocks in `photoz/bses/kafka.py` across `publish_kafka_event`, `handle`, and `handle_payloads` to conform to the canonical `[call, return]` pattern, resolving pattern fragmentation drift.
    *   Updated `chapter06/kafka/README.md` with execution and verification details for Phase 4.
*   **Notes/Edge Cases**:
    *   Resolving error handling pattern fragmentation in `bses/kafka.py` ensured the drift-check gate passed without needing to modify `.drift-baseline.json`.
    *   All 6 pre-commit checks (`ruff`, `ruff-format`, `pylint`, `import-linter`, `drift-check`, `calm-validate`) pass cleanly with exit code 0.

## Phase: Phase 5: Dead Letter Queue (DLQ) & Retry Policy (Date: 2026-10-11, Commit: b789d1a22b532ecaccac1ce317799cf3d159f55e, Model: Gemini 3.1 Pro High)
*   **Rationale**: Prevent consumer crashes, infinite retry loops, and unobserved data loss from poison pills (e.g. database foreign key violations) or transient database errors by adding exponential backoff retries and routing unprocessable messages to Dead Letter Queue topics.
*   **Actions**:
    *   Implemented `publish_to_dlq` in `photoz/bses/kafka.py` wrapping failed messages with a diagnostic envelope (`original_topic`, `original_payload`, `error_type`, `error_message`, `timestamp`, `retry_count`) and producing to `{topic}.dlq`.
    *   Added exponential backoff retries to `BaseKafkaConsumerCommand` for transient database errors (`max_retries = 3`, `retry_backoff_base = 0.5s`).
    *   Updated `_extract_payloads` to catch corrupted JSON bytes and publish them directly to DLQ.
    *   Updated `handle_payloads` to validate required schema keys and route malformed payloads to DLQ.
    *   Enhanced `_fallback_persist` and `_persist_single` to catch `IntegrityError` (foreign key violations) and unrecoverable `DatabaseError`, routing the poisoned record to DLQ and committing partition offsets so consumers do not deadlock.
    *   Standardized error handling blocks to adhere to canonical `[call, return]` AST pattern.
    *   Verified all 6 pre-commit hooks (`ruff`, `ruff-format`, `pylint`, `import-linter`, `drift-check`, `calm-validate`) pass cleanly with exit code 0.
    *   Updated `chapter06/kafka/README.md` with DLQ inspection and testing instructions.
*   **Notes/Edge Cases**:
    *   Lines in docstrings and string formatters exceeding 100 characters caused Ruff line-length failures; refactored to multiline formatting.
    *   Confirmed end-to-end routing in Kafka cluster: malformed payloads, non-JSON bytes, and non-existent foreign keys were isolated in `photo.events.likes.dlq` without interrupting valid message processing.

## Phase: Phase 6: Celery Decommissioning - Part 1: Workflow Migration (Date: 2026-10-11, Commit: 2b8f4ef, Model: Gemini 3.1 Pro High)
*   **Rationale**: Eliminate Celery operational overhead, Redis queue resource consumption, and duplicate worker architectures by migrating all asynchronous tasks (notifications, photo deletions, counter synchronizations) to Kafka topics and consumers.
*   **Actions**:
    *   Configured and provisioned `photo.events.notifications` and `photo.events.deletions` topics and their `.dlq` counterparts in `photoz/bses/settings.py` and `photoz/kafka_setup.py`.
    *   Migrated notification creation logic from Celery tasks into `photoz/notifications/services.py`, updated `notifications/signals.py` to publish to Kafka, and created `run_notifications_consumer` daemon.
    *   Migrated follower newsfeed cache invalidation on photo deletions into `photoz/newsfeed/services.py`, updated `newsfeed/signals.py` to publish to Kafka, and created `run_deletions_consumer` daemon.
    *   Updated `photos/services.py:bulk_record_likes` to atomically increment `Photo.likes_count` in PostgreSQL on batch consumption, matching `bulk_record_follows` and rendering periodic Celery Beat flushes obsolete.
    *   Decommissioned Celery task files (`notifications/tasks.py`, `newsfeed/tasks.py`, `photos/tasks.py`, `users/tasks.py`).
    *   Removed `CELERY_BEAT_SCHEDULE` and all `CELERY_*` settings from `photoz/bses/settings.py`, removed `photoz/bses/celery.py`, and cleaned `photoz/bses/__init__.py`.
    *   Updated `photoz/.importlinter` rules to maintain clean domain app boundaries.
    *   Updated `chapter06/kafka/README.md` and verified all 6 pre-commit hooks pass cleanly with code 0.
*   **Notes/Edge Cases**:
    *   `run_notifications_consumer` overrides `handle_payloads` to process dictionary payloads with varied event schemas (`photo_activity`, `member_invited`, `tagged`), providing modular extensible event handling while maintaining the standard consumer lifecycle.

## Phase: Phase 6: Celery Decommissioning - Part 2: Infrastructure & Dependency Removal (Date: 2026-10-12, Commit: 456e684, Model: Gemini 3.1 Pro High)
*   **Rationale**: Complete Celery retirement by purging obsolete Celery/Flower container services, removing Celery packages from dependencies, and removing Celery Beat security group ingress rules in Terraform.
*   **Actions**:
    *   Removed `celery`, `celery-beat`, and `flower` services from `photoz/docker-compose.yml`.
    *   Removed `celery` and `celery-beat` services from `photoz/docker-compose-app.yml`.
    *   Removed `celery>=5.3.6`, `celery-redbeat>=2.2.0`, and `flower` from `photoz/requirements.txt`, retaining `redis>=5.0.1` for newsfeed caching and session handling.
    *   Removed obsolete Celery Beat security group ingress rules from the Redis node to PostgreSQL (5432) and PgBouncer (6432) in `iaac/aws/terraform/security.tf`.
    *   Updated `chapter06/kafka/README.md` to document infrastructure and dependency removal.
    *   Verified all 6 pre-commit checks (`ruff`, `ruff-format`, `pylint`, `import-linter`, `drift-check`, `calm-validate`) pass cleanly with exit code 0.
*   **Notes/Edge Cases**:
    *   `redis` service in `docker-compose.yml` and `redis>=5.0.1` in `requirements.txt` are maintained because Redis remains actively used for caching newsfeeds and distributed locks.

## Phase: Phase 7: AWS Infrastructure Deployment (Terraform & KRaft EC2) - Plan Generation (Date: 2026-10-12, Commit: 05e0bb6, Model: Gemini 3.1 Pro High)
*   **Rationale**: Deploying Kafka for production workloads requires resilient consensus, isolation between control operations and high-throughput data operations, fault tolerance across data centers, and persistent high-speed disk storage.
*   **Actions**:
    *   Designed Terraform architecture for KRaft mode: 3 controllers forming a consensus quorum and 3 data brokers handling message log I/O.
    *   Formulated 5-task implementation plan covering multi-AZ subnets, security groups, EC2 instances with gp3 EBS volumes, app node bootstrap injection, outputs, and validation.
    *   Documented plan in `chapter06/kafka/implementation-v0.md` and `photoz/skills/implementation-v0.md`.
*   **Notes/Edge Cases**:
    *   Predictable private IP addressing for controllers eliminates circular dependency in the `KAFKA_CONTROLLER_QUORUM_VOTERS` configuration.

## Phase: Phase 7: AWS Infrastructure Deployment (Terraform & KRaft EC2) (Date: 2026-10-12, Commit: c2c940e, Model: Gemini 3.1 Pro High)
*   **Rationale**: Provision a production-ready, self-managed Apache Kafka cluster in KRaft mode on AWS EC2, strictly decoupling the metadata consensus control plane from the high-throughput data brokers across 3 Availability Zones.
*   **Actions**:
    *   Expanded `aws_subnet.public` and route table associations in `iaac/aws/terraform/network.tf` from 2 to 3 to span 3 distinct Availability Zones.
    *   Added Kafka cluster configuration variables in `iaac/aws/terraform/variables.tf` (`create_kafka_cluster`, `kafka_key_name`, instance types, EBS size).
    *   Configured dedicated security groups in `iaac/aws/terraform/security.tf`: `photoz-kafka-controller-sg` (port 9093 internal quorum) and `photoz-kafka-broker-sg` (port 9092 PLAINTEXT accessible to App nodes and brokers).
    *   Created `iaac/aws/terraform/kafka.tf` provisioning 3 dedicated KRaft Controllers (`t3.medium`) and 3 dedicated Brokers (`t3.medium`) with gp3 EBS volumes (`/var/lib/kafka/data`), deterministic private IPs, and Docker KRaft automated user_data.
    *   Updated App Node launch template in `iaac/aws/terraform/main.tf` to inject `KAFKA_BOOTSTRAP_SERVERS` into `.env`.
    *   Added outputs in `iaac/aws/terraform/outputs.tf` for controller IPs, broker IPs, and bootstrap servers.
    *   Documented deployment and verification commands in `chapter06/kafka/README.md`.
    *   Validated Terraform configuration (`terraform validate`) and verified all 6 pre-commit hooks pass cleanly with exit code 0.
*   **Notes/Edge Cases**:
    *   Using static private IP mapping (`10.0.${i}.20` for controllers, `10.0.${i}.30` for brokers) eliminated circular dependencies during quorum voter configuration and bootstrap discovery.
    *   EBS attachment script in broker user_data dynamically accommodates both standard xen (`/dev/xvdf`) and Nitro NVMe (`/dev/nvme*n1`) device paths.

## Phase: Phase 7: Kafka Broker Log Directory Isolation & PgBouncer Post-Restart Pool Reset (Date: 2026-10-12, Commit: c7799f5, Model: Gemini 3.1 Pro High)
*   **Rationale**: Fix runtime failures on AWS deployment where Kafka brokers crash on startup due to ext4 filesystem artifacts and Django fails to query the database due to cached DNS/login errors in PgBouncer.
*   **Actions**:
    *   Updated `iaac/aws/terraform/kafka.tf` user_data to isolate Kafka log storage into `/var/lib/kafka/data/kafka` and set `KAFKA_LOG_DIRS=/var/lib/kafka/data/kafka`, preventing `lost+found` at the EBS mount root from crashing Kafka LogManager.
    *   Added `CLUSTER_ID` alongside `KAFKA_CLUSTER_ID` in `kafka.tf` docker environments for strict container script compatibility.
    *   Updated `iaac/aws/terraform/main.tf` to restart PgBouncer (`docker compose -f docker-compose-db.yml restart pgbouncer`) after the PostgreSQL restart check passes, resetting stale DNS and cached connection errors.
*   **Notes/Edge Cases**:
    *   Kafka requires log directories to contain only topic-partition folders; mounting an ext4 volume at the root of `KAFKA_LOG_DIRS` causes `KafkaException: Found directory lost+found`. Isolate Kafka data to a child directory to insulate against filesystem artifacts.

## Phase: Phase 7: Kafka Consumer Auto-Orchestration & Idempotent Like Counter Fix (Date: 2026-10-12, Commit: 8415f06d4125acd207b5756db56e235f19651b77, Model: Gemini 3.1 Pro High)
*   **Rationale**: Fix UI bug where like count increments infinitely on repetitive clicks due to absence of running Kafka consumers and lack of idempotent state tracking, and resolve query_wait_timeout caused by Postgres connection pool starvation.
*   **Actions**:
    *   Added `consumers` service to `photoz/docker-compose-app.yml` executing all 5 Kafka consumer daemons (`run_kafka_consumers`, `run_followers_consumer`, `run_uploads_consumer`, `run_notifications_consumer`, `run_deletions_consumer`) under Docker process supervision.
    *   Implemented `is_photo_liked_by_user` and `toggle_photo_like_redis` in `photoz/photos/services.py` using Redis sets (`photo:{photo_id}:likers`) to track per-user like state in memory and guarantee strictly idempotent toggling.
    *   Updated `toggle_like` and `photo_detail` in `photoz/photos/views.py` to use Redis-backed state, preventing duplicate clicks from inflating the counter or bypassing unliking.
    *   Updated `bulk_record_likes` in `photos/services.py` to deduplicate batches and only increment `Photo.likes_count` by genuinely new insertions.
    *   Increased PostgreSQL `max_connections` from 20 to 100 in `photoz/docker-compose-db.yml`, `docker-compose.yml`, and `docker-compose-replica.yml`.
    *   Added `admin_users` and `stats_users` to `pgbouncer.ini` and `pgbouncer-replica.ini` and scaled `default_pool_size` to 25.
*   **Notes/Edge Cases**:
    *   Redis sets provide instantaneous sub-millisecond like state resolution while Kafka consumes and writes in the background, preventing race conditions during rapid clicking.

## Phase: C4 Model & CALM Architecture Update with Kafka Integration (Date: 2026-10-13, Commit: 7e5befea900cdbac5623defc3046cc405d022f91, Model: Gemini 3.8 Flash High)
*   **Rationale**: Bring architecture models into full alignment with the Celery decommission and Kafka KRaft cluster integration, and provide clear operational documentation for generating C4 diagrams and validating CALM schemas.
*   **Actions**:
    *   Updated Structurizr C4 model in `photoz/structurizr/workspace.dsl` removing obsolete Celery Worker and Celery Beat containers, adding Kafka Consumers on App nodes and Kafka Cluster (KRaft), updating event publish/consume relationships, and adding Queue element styling.
    *   Updated FINOS CALM architecture model in `photoz/architecture/photoz.calm.json` replacing Celery service nodes with `kafka-cluster` and `kafka-consumers`, and updating relationship topologies for TCP event publishing, consumption, and cache invalidation.
    *   Updated Mermaid diagrams and node links in `photoz/architecture/docs/docs/index.md` to reflect the Kafka architecture.
    *   Updated `photoz/README.md` adding instructions for running the Structurizr C4 viewer locally via Docker, generating Level 4 ER code diagrams with `graph_models`, validating CALM models with `@finos/calm-cli`, and serving the documentation site.
    *   Set Structurizr C4 element styles and Mermaid nodes to plain white backgrounds (`#ffffff`), black text (`#000000`), and black borders (`#000000`).
*   **Notes/Edge Cases**:
    *   CALM guardrail validation (`guardrails.pattern.json`) confirms zero direct writes to replicas and strict S3 access isolation through the CDN.

## Phase: Phase 8: Kafka Queue & Lag Metrics via CloudWatch EMF (Date: 2026-10-17, Commit: Pending, Model: Gemini 3.8 Flash High)
*   **Rationale**: Expose queue backlog, consumer lag, and processing delay metrics without incurring high custom metric storage costs or network latency by aggregating metrics at the topic level and emitting CloudWatch Embedded Metric Format (EMF) JSON to stdout.
*   **Actions**:
    *   Created `photoz/bses/apps.py` registering `BsesConfig` and added `bses.apps.BsesConfig` to `INSTALLED_APPS` in `photoz/bses/settings.py`.
    *   Configured `consumer_group` mappings for all topics in `KAFKA_TOPICS` and set `KAFKA_METRICS_INTERVAL_SECONDS = 60` in `photoz/bses/settings.py`.
    *   Implemented `photoz/bses/kafka_metrics.py` providing watermark queries, offset comparisons, record age timestamp extraction, DLQ depth calculation, and CloudWatch EMF payload formatting.
    *   Implemented `photoz/bses/management/commands/run_kafka_metrics.py` supporting one-shot execution (`--once`) and continuous daemon monitoring polling every 60 seconds.
    *   Updated `BaseKafkaConsumerCommand` in `photoz/bses/kafka.py` to calculate batch `TimeLagSeconds` based on Kafka message timestamps and emit EMF telemetry upon batch commit.
    *   Updated `photoz/docker-compose-app.yml` adding `python manage.py run_kafka_metrics &` to the `consumers` service container command.
    *   Created `iaac/aws/terraform/kafka_monitoring.tf` provisioning CloudWatch Metric Alarms for consumer lag (>5,000 messages), time lag (>300 seconds), and DLQ accumulation (>0 messages), plus a unified CloudWatch dashboard.
    *   Created unit tests in `photoz/tests/test_kafka_metrics.py` and `photoz/tests/test_kafka_metrics_command.py` with negative assertions for polarity validation.
    *   Refactored `photoz/bses/kafka_metrics.py` extracting helper functions (`_compute_partition_lags`, `_collect_single_topic_metrics`, `_query_watermarks`, `_query_committed`, `_poll_partition_timestamp`) to reduce local variable counts below Pylint limit and achieve 10.00/10 rating.
    *   Standardized error handling blocks in `kafka_metrics.py` and `run_kafka_metrics.py` to adhere to canonical `[call, return]` AST pattern, resolving pattern fragmentation drift.
    *   Verified all 6 pre-commit hooks (`ruff`, `ruff-format`, `pylint`, `import-linter`, `drift-check`, `calm-validate`) pass cleanly with exit code 0.
*   **Notes/Edge Cases**:
    *   Uncommitted consumer groups report `-1001` (`OFFSET_INVALID`); handled by falling back to partition low watermark so lag defaults correctly without negative values.
    *   Negative assertions added to tests resolved `test_polarity_deficit` drift finding without modifying `.drift-baseline.json`.
    *   Decomposed metric gathering loops into dedicated helpers to eliminate `R0914 (too-many-locals)` and aligned exception handlers with canonical `call` and `return` actions.







