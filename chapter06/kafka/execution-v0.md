
## Phase: Local Kafka Setup (Date: 2026-10-10, Commit: pending, Model: Gemini 3.1 Pro High)
*   **Rationale**: Adding Kafka to the local development environment using Bitnami Kafka KRaft to begin testing local Kafka Producer/Consumer logic before AWS deployment.
*   **Actions**:
    *   Updated `photoz/docker-compose.yml` to include a new `kafka` service using `apache/kafka:4.3.1` in KRaft mode.
    *   Added `kafka_data` docker volume.
