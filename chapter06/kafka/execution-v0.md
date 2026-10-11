
## Phase: Local Kafka Setup (Date: 2026-10-10, Commit: 02a185909e1b07c9830c2c692e07645b2e6d6b0d, Model: Gemini 3.1 Pro High)
*   **Rationale**: Adding Kafka to the local development environment using Bitnami Kafka KRaft to begin testing local Kafka Producer/Consumer logic before AWS deployment.
*   **Actions**:
    *   Updated `photoz/docker-compose.yml` to include a new `kafka` service using `apache/kafka:4.3.1` in KRaft mode.
    *   Added `kafka_data` docker volume.

## Phase: Phase 2: Kafka Consumers and Topic Setup (Date: 2026-10-11, Commit: Pending, Model: Gemini 3.1 Pro High)
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
