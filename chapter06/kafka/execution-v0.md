
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

## Phase: Phase 3: Kafka Producers Implementation (Date: 2026-10-11, Commit: Pending, Model: Gemini 3.1 Pro High)
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

