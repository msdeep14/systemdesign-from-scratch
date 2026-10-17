# Phase 6: Celery Decommissioning (Part 1: Workflow Migration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all remaining Celery-dependent workflows (notifications, newsfeed photo deletions, and like/follower count flushes) to Kafka topics and consumers, completely removing Celery tasks and dependencies from the application codebase.

**Architecture:** 
1. Provision Kafka topics `photo.events.notifications` and `photo.events.deletions` with associated DLQs.
2. Replace Celery notification tasks with Kafka event emission in `notifications/signals.py` and consume via a dedicated `run_notifications_consumer` daemon.
3. Replace Celery photo deletion fanout with Kafka event emission in `newsfeed/signals.py` and consume via `run_deletions_consumer`.
4. Update `bulk_record_likes` in `photos/services.py` to atomically maintain `Photo.likes_count` in PostgreSQL on batch consumption, eliminating periodic Celery Beat flushes for both likes and follower counts.
5. Decommission all Celery task files (`notifications/tasks.py`, `newsfeed/tasks.py`, `photos/tasks.py`, `users/tasks.py`), remove `bses/celery.py`, clear `bses/__init__.py`, and remove Celery settings.

**Tech Stack:** Python 3.12, confluent-kafka, Django 5.0, PostgreSQL, Apache Kafka 4.3.1 (KRaft), Redis.

**Spec:** Chapter 6 - Celery Decommissioning & Asynchronous Workflow Migration.

## Global Constraints
- Code changes must adhere to the modular monolith boundaries enforced by `import-linter`.
- Pylint rating must remain at 10.00/10.
- All `try/except` blocks in `bses/kafka.py` and consumers must conform to the canonical `[call, return]` pattern to satisfy `drift-analyzer`.
- No auto-commit. The user will review and commit manually.
- Plain English documentation and logs only; no emojis.

---

### Task 1: Kafka Topics Configuration & Provisioning
**Files:**
- Modify: `photoz/bses/settings.py`
- Modify: `photoz/kafka_setup.py`

**Interfaces:**
- Adds topic configurations:
  - `"notifications"`: `photo.events.notifications` (50 partitions, dlq=True)
  - `"deletions"`: `photo.events.deletions` (50 partitions, dlq=True)

- [x] **Step 1: Add new topics to `settings.py` and `kafka_setup.py`**
  Update `KAFKA_TOPICS` in `photoz/bses/settings.py` and `DEFAULT_TOPICS` in `photoz/kafka_setup.py`.
- [x] **Step 2: Run `kafka_setup.py` to provision topics in Kafka**
  Execute `kafka_setup.py` to create `photo.events.notifications`, `photo.events.deletions`, and their corresponding `.dlq` topics.

---

### Task 2: Migrate Notifications Workflow to Kafka
**Files:**
- Modify: `photoz/notifications/signals.py`
- Modify: `photoz/notifications/services.py`
- Create: `photoz/notifications/management/commands/run_notifications_consumer.py`
- Delete: `photoz/notifications/tasks.py`
- Modify: `photoz/.importlinter`

**Interfaces:**
- Produces: Kafka event payloads on `photo.events.notifications`
- Consumes: `bulk_create_notifications(events: list[dict]) -> int` in `notifications/services.py`

- [x] **Step 1: Implement notification creation service**
  Implement `bulk_create_notifications(events: list[dict]) -> int` in `photoz/notifications/services.py`, creating `Notification` objects for photo activities, community invites, and tagging events.
- [x] **Step 2: Update `notifications/signals.py` to publish to Kafka**
  Replace `.delay()` task invocations with `publish_kafka_event("notifications", payload, key=str(recipient_id))`.
- [x] **Step 3: Create `run_notifications_consumer` management command**
  Create `photoz/notifications/management/commands/run_notifications_consumer.py` inheriting from `BaseKafkaConsumerCommand` to consume and process notification events.
- [x] **Step 4: Remove `notifications/tasks.py` and update `.importlinter`**
  Delete `photoz/notifications/tasks.py` and update `.importlinter` ignore rules to reference `notifications.services` instead of `notifications.tasks`.

---

### Task 3: Migrate Newsfeed Photo Deletions Workflow to Kafka
**Files:**
- Modify: `photoz/newsfeed/signals.py`
- Modify: `photoz/newsfeed/services.py`
- Create: `photoz/newsfeed/management/commands/run_deletions_consumer.py`
- Delete: `photoz/newsfeed/tasks.py`

**Interfaces:**
- Produces: Kafka event payloads on `photo.events.deletions`
- Consumes: `bulk_invalidate_follower_feed_caches(records: list[tuple[int, int]]) -> int` in `newsfeed/services.py`

- [x] **Step 1: Implement bulk feed cache invalidation service**
  Add `bulk_invalidate_follower_feed_caches(records: list[tuple[int, int]]) -> int` in `photoz/newsfeed/services.py`.
- [x] **Step 2: Update `newsfeed/signals.py` to publish to Kafka**
  Replace `fanout_photo_deleted_task.delay(user.id)` with `publish_kafka_event("deletions", {"user_id": user.id, "photo_id": photo_id or 0}, key=str(user.id))`.
- [x] **Step 3: Create `run_deletions_consumer` management command**
  Create `photoz/newsfeed/management/commands/run_deletions_consumer.py` inheriting from `BaseKafkaConsumerCommand`.
- [x] **Step 4: Remove `newsfeed/tasks.py`**
  Delete `photoz/newsfeed/tasks.py`.

---

### Task 4: Atomic Counters in Database & Celery Beat Elimination
**Files:**
- Modify: `photoz/photos/services.py`
- Delete: `photoz/photos/tasks.py`
- Delete: `photoz/users/tasks.py`
- Modify: `photoz/bses/settings.py`
- Delete: `photoz/bses/celery.py`
- Modify: `photoz/bses/__init__.py`

**Interfaces:**
- Modifies: `bulk_record_likes` in `photos/services.py` to atomically update `Photo.likes_count` in PostgreSQL.

- [x] **Step 1: Update `bulk_record_likes` to maintain atomic counts**
  Update `bulk_record_likes` in `photos/services.py` to increment `Photo.likes_count` via `F("likes_count") + count` inside the atomic transaction, matching `bulk_record_follows`.
- [x] **Step 2: Delete `photos/tasks.py` and `users/tasks.py`**
  Remove periodic flush task files.
- [x] **Step 3: Remove Celery configuration and files**
  Remove `CELERY_BEAT_SCHEDULE` and all `CELERY_*` settings from `photoz/bses/settings.py`. Delete `photoz/bses/celery.py` and clear Celery exports from `photoz/bses/__init__.py`.

---

### Task 5: Verification & Pre-Commit Validation
**Files:**
- Run verification across the codebase.

- [x] **Step 1: Test notification and deletion events end-to-end**
  Publish test events to `photo.events.notifications` and `photo.events.deletions` and verify consumer execution.
- [x] **Step 2: Run all 6 pre-commit hooks**
  Run `ruff`, `ruff-format`, `pylint`, `import-linter`, `drift-check`, and `calm-validate`.

---

### Task 6: Documentation & Execution Logging
**Files:**
- Modify: `chapter06/kafka/README.md`
- Modify: `chapter06/kafka/execution-v0.md`
- Modify: `photoz/skills/execution-v0.md`
- Modify: `photoz/skills/implementation-v0.md`

- [x] **Step 1: Update README.md**
  Document the newly migrated notifications and deletions consumers, topics, and message formats.
- [x] **Step 2: Append execution log entries**
  Log actions and decisions in `chapter06/kafka/execution-v0.md` and `photoz/skills/execution-v0.md`.

---

### Task 7: Celery Infrastructure & Dependency Removal (Part 2)
**Files:**
- Modify: `photoz/requirements.txt`
- Modify: `photoz/docker-compose.yml`
- Modify: `photoz/docker-compose-app.yml`
- Modify: `iaac/aws/terraform/security.tf`
- Modify: `chapter06/kafka/README.md`

- [x] **Step 1: Remove Celery packages from requirements.txt**
  Purge `celery`, `celery-redbeat`, and `flower` from `photoz/requirements.txt` while retaining `redis>=5.0.1`.
- [x] **Step 2: Clean docker compose definitions**
  Remove `celery`, `celery-beat`, and `flower` services from `photoz/docker-compose.yml` and `photoz/docker-compose-app.yml`.
- [x] **Step 3: Remove Celery Beat ingress rules from Terraform**
  Remove Postgres and PgBouncer ingress blocks for the Redis node in `iaac/aws/terraform/security.tf`.
- [x] **Step 4: Verification & Logging**
  Run all 6 pre-commit checks and append execution logs.

---

# Phase 7: AWS Infrastructure Deployment (Terraform & KRaft EC2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision a fault-tolerant, self-managed Apache Kafka cluster in KRaft mode on AWS EC2 using Terraform, isolating the Control Plane (3 KRaft Controllers) from the Data Plane (3 Brokers) across 3 Availability Zones with dedicated gp3 EBS volumes.

**Architecture:** 
1. Subnets in `network.tf` expanded to 3 public subnets across 3 Availability Zones (`ap-south-1a`, `ap-south-1b`, `ap-south-1c`).
2. Security groups: `photoz-kafka-controller-sg` (port 9093 internal quorum between controllers and brokers) and `photoz-kafka-broker-sg` (port 9092 PLAINTEXT accessible to App nodes and brokers).
3. 3 dedicated EC2 instances for KRaft Controllers (`process.roles=controller`, IDs 1, 2, 3) running across the 3 subnets.
4. 3 dedicated EC2 instances for KRaft Brokers (`process.roles=broker`, IDs 101, 102, 103) running across the 3 subnets with dedicated gp3 EBS volumes for persistent commit logs.
5. Launch template for App nodes updated to dynamically receive `KAFKA_BOOTSTRAP_SERVERS` pointing to all 3 broker private IPs.
6. Terraform outputs and variables defined for cluster toggles, instance types, and bootstrap addresses.

**Tech Stack:** Terraform, AWS EC2, AWS EBS (gp3), AWS VPC, Apache Kafka 4.3.1 (KRaft mode via Docker Engine), Ubuntu 24.04.

**Spec:** Chapter 6 - Phase 7 AWS Infrastructure Deployment (`kafka_implementation_details.md`).

## Global Constraints
- Preserve existing Terraform resources and variables without breaking backwards compatibility.
- Never hardcode credentials or secrets; use IAM instance profile and AWS SSM.
- Pylint rating must remain at 10.00/10.
- All 6 pre-commit checks (`ruff`, `ruff-format`, `pylint`, `import-linter`, `drift-check`, `calm-validate`) must pass.
- No auto-commit. The user reviews and commits manually.
- Plain English only; no emojis.

---

### Task 1: Expand Subnets across 3 Availability Zones
**Files:**
- Modify: `iaac/aws/terraform/network.tf`

**Interfaces:**
- Consumes: `data.aws_availability_zones.available.names`
- Produces: `local.subnet_ids` with 3 subnets across 3 distinct AZs

- [x] **Step 1: Update subnet count and route table associations**
  Update `aws_subnet.public` count from 2 to 3, and `aws_route_table_association.public` count from 2 to 3 in `network.tf`.

---

### Task 2: Configure Terraform Variables & Security Groups
**Files:**
- Modify: `iaac/aws/terraform/variables.tf`
- Modify: `iaac/aws/terraform/security.tf`

**Interfaces:**
- Produces: `local.kafka_controller_sg_id`, `local.kafka_broker_sg_id`

- [x] **Step 1: Define Kafka variables in variables.tf**
  Add `create_kafka_cluster`, `kafka_key_name`, `kafka_controller_instance_type`, `kafka_broker_instance_type`, `kafka_ebs_volume_size`.
- [x] **Step 2: Define Controller and Broker Security Groups in security.tf**
  Create `aws_security_group.kafka_controller` (port 9093 from controllers and brokers, port 22 from admin IP) and `aws_security_group.kafka_broker` (port 9092 from App SG and broker SG, port 22 from admin IP).

---

### Task 3: Provision KRaft Controllers & Brokers in Terraform
**Files:**
- Create: `iaac/aws/terraform/kafka.tf`

**Interfaces:**
- Produces: `aws_instance.kafka_controller[3]`, `aws_instance.kafka_broker[3]`, `aws_ebs_volume.kafka_broker_data[3]`

- [x] **Step 1: Write Controller provisioning with KRaft quorum user_data**
  Provision 3 controller EC2 instances across the 3 subnets with predictable IPs (`10.0.0.20`, `10.0.1.20`, `10.0.2.20`) and user_data launching `apache/kafka:4.3.1` in controller mode.
- [x] **Step 2: Write Broker provisioning with gp3 EBS volumes and user_data**
  Provision 3 broker EC2 instances across the 3 subnets (`10.0.0.30`, `10.0.1.30`, `10.0.2.30`) with dedicated attached 50GB gp3 EBS volumes mounted at `/var/lib/kafka/data`, running `apache/kafka:4.3.1` in broker mode with replication factor 3.

---

### Task 4: Connect App Nodes & Define Terraform Outputs
**Files:**
- Modify: `iaac/aws/terraform/main.tf`
- Modify: `iaac/aws/terraform/outputs.tf`

**Interfaces:**
- Produces: `KAFKA_BOOTSTRAP_SERVERS` injected into `app_node` `.env`, and outputs `kafka_bootstrap_servers`, `kafka_controller_private_ips`, `kafka_broker_private_ips`.

- [x] **Step 1: Update App Node launch template user_data**
  Inject `KAFKA_BOOTSTRAP_SERVERS` into App Node `.env` referencing broker private IPs.
- [x] **Step 2: Add outputs in outputs.tf**
  Add outputs for broker IPs, controller IPs, and bootstrap connection string.

---

### Task 5: Verification, Execution Logging & Documentation
**Files:**
- Modify: `chapter06/kafka/README.md`
- Modify: `chapter06/kafka/execution-v0.md`
- Modify: `photoz/skills/execution-v0.md`
- Run: `pre-commit run --all-files`

- [x] **Step 1: Run pre-commit checks**
  Verify all 6 hooks pass cleanly.
- [x] **Step 2: Document Phase 7 deployment in README.md**
  Add AWS deployment instructions, architecture description, and validation commands to `chapter06/kafka/README.md`.
- [x] **Step 3: Update execution logs**
  Log actions and decisions in `chapter06/kafka/execution-v0.md` and `photoz/skills/execution-v0.md`.

---

# Phase 8: Kafka Queue & Lag Metrics via CloudWatch EMF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect and export queue backlog, consumer lag, message time lag, and dead-letter queue metrics across all Kafka topics to AWS CloudWatch using Embedded Metric Format (EMF), with automated CloudWatch alarms and monitoring dashboards.

**Architecture:** 
1. Maintain cost efficiency by aggregating 250 partition streams into Topic + Consumer Group dimensions, keeping CloudWatch custom metric counts under 10 ($3/month).
2. A standalone monitoring command (`run_kafka_metrics`) queries partition watermarks and committed consumer group offsets via Kafka client APIs, computes `ConsumerLag`, `MaxPartitionLag`, `LogEndOffset`, `TimeLagSeconds`, and `DLQDepth`, and emits EMF JSON logs to `stdout`.
3. In-flight consumer loops in `BaseKafkaConsumerCommand` calculate real-time batch `TimeLagSeconds` based on record creation timestamps and emit EMF telemetry upon batch commit.
4. Add the metrics daemon to `docker-compose-app.yml` to run under container process supervision and stream to CloudWatch Logs via Docker's `awslogs` driver.
5. Provision Terraform CloudWatch Alarms for backlog spikes, stalled consumers, and poison pills, accompanied by a unified Kafka health dashboard.

**Tech Stack:** Python 3.12, confluent-kafka 2.16.0, Django 5.0, AWS CloudWatch (EMF, Metrics, Alarms), Terraform.

**Spec:** Chapter 6 - Phase 8: Kafka Queue & Observability System.

## Global Constraints
- Code changes must adhere to modular monolith boundaries enforced by `import-linter`.
- Pylint score must remain at 10.00/10.
- All `try/except` blocks must conform to the canonical `[call, return]` pattern to satisfy `drift-analyzer`.
- No auto-commit. The user will review and commit manually.
- Plain English documentation and logs only; no emojis in code or messages.
- No inline imports. All imports must be declared at the top of the file.

---

### Task 1: Core Kafka Metrics Collector Service & App Configuration
**Files:**
- Create: `photoz/bses/apps.py`
- Modify: `photoz/bses/settings.py`
- Create: `photoz/bses/kafka_metrics.py`
- Create: `photoz/tests/test_kafka_metrics.py`

**Interfaces:**
- Produces: `collect_all_kafka_metrics(bootstrap_servers: str | None = None) -> list[dict[str, Any]]`
- Produces: `compute_topic_metrics(topic_name: str, consumer_group: str, num_partitions: int, consumer: Any) -> dict[str, Any]`
- Produces: `compute_dlq_metrics(dlq_topic_name: str, num_partitions: int, consumer: Any) -> dict[str, Any]`

- [x] **Step 1: Write unit tests for metric computation and EMF formatting**
  Create `photoz/tests/test_kafka_metrics.py` testing partition lag calculation, handling of uncommitted offsets (`-1001`), `MaxPartitionLag`, `DLQDepth`, and EMF JSON structure validation.
- [x] **Step 2: Run test to verify it fails**
  Run: `source ./photoz/venv/bin/activate && cd photoz && pytest tests/test_kafka_metrics.py`
  Expected: FAIL with ModuleNotFoundError or ImportError.
- [x] **Step 3: Create `bses/apps.py` and register in `settings.py`**
  Create `BsesConfig` in `photoz/bses/apps.py` and add `"bses.apps.BsesConfig"` to `INSTALLED_APPS` in `photoz/bses/settings.py`. Add `KAFKA_METRICS_INTERVAL_SECONDS = 60` to settings.
- [x] **Step 4: Implement `photoz/bses/kafka_metrics.py`**
  Implement watermark queries, offset comparisons, record age timestamp checks, and EMF payload formatting.
- [x] **Step 5: Run tests to verify they pass**
  Run: `source ./photoz/venv/bin/activate && cd photoz && pytest tests/test_kafka_metrics.py`
  Expected: PASS.

---

### Task 2: Management Command `run_kafka_metrics` & Consumer Batch Telemetry
**Files:**
- Create: `photoz/bses/management/commands/run_kafka_metrics.py`
- Modify: `photoz/bses/kafka.py`
- Create: `photoz/tests/test_kafka_metrics_command.py`

**Interfaces:**
- Command: `python manage.py run_kafka_metrics [--once]`
- Emits: EMF JSON objects to `metrics` logger (`PhotoZ/Kafka` namespace).
- Consumer metric: `BaseKafkaConsumerCommand` emits batch `TimeLagSeconds` and `BatchSize`.

- [x] **Step 1: Write test for `run_kafka_metrics` management command**
  Create `photoz/tests/test_kafka_metrics_command.py` verifying `--once` execution and stdout EMF logging.
- [x] **Step 2: Implement `run_kafka_metrics.py` command**
  Add Django management command with `--once` flag and daemon loop polling every `KAFKA_METRICS_INTERVAL_SECONDS`.
- [x] **Step 3: Update `BaseKafkaConsumerCommand` in `bses/kafka.py`**
  Compute batch message age (`TimeLagSeconds`) from record timestamps and emit batch metrics on commit.
- [x] **Step 4: Run command tests to verify they pass**
  Run: `source ./photoz/venv/bin/activate && cd photoz && pytest tests/test_kafka_metrics_command.py`
  Expected: PASS.

---

### Task 3: Container Orchestration & Docker Compose
**Files:**
- Modify: `photoz/docker-compose-app.yml`

**Interfaces:**
- Daemon execution: `python manage.py run_kafka_metrics &` supervised in `consumers` service container.

- [x] **Step 1: Update `consumers` service command in `docker-compose-app.yml`**
  Add `python manage.py run_kafka_metrics &` before `wait -n`.

---

### Task 4: Terraform CloudWatch Alarms & Monitoring Dashboard
**Files:**
- Create: `iaac/aws/terraform/kafka_monitoring.tf`

**Interfaces:**
- Produces: `aws_cloudwatch_metric_alarm.kafka_high_lag`, `aws_cloudwatch_metric_alarm.kafka_high_timelag`, `aws_cloudwatch_metric_alarm.kafka_dlq_alert`, `aws_cloudwatch_dashboard.kafka_metrics`.

- [x] **Step 1: Create `kafka_monitoring.tf` in Terraform**
  Configure CloudWatch Metric Alarms for high consumer lag (>5,000 for 2 periods), high time lag (>300s for 2 periods), and DLQ poison pills (>0 for 1 period). Add a CloudWatch dashboard showing lag by topic, max partition skew, and DLQ depth.
- [x] **Step 2: Validate Terraform configuration**
  Run: `cd iaac/aws/terraform && terraform validate`
  Expected: Success.

---

### Task 5: End-to-End Verification, Execution Logging & Documentation
**Files:**
- Modify: `chapter06/kafka/execution-v0.md`
- Modify: `photoz/skills/execution-v0.md`
- Modify: `chapter06/kafka/README.md`
- Run: `pre-commit run --all-files`

- [x] **Step 1: Run all pre-commit checks**
  Run: `source ./photoz/venv/bin/activate && pre-commit run --all-files`
  Verify all 6 checks (`ruff`, `ruff-format`, `pylint`, `import-linter`, `drift-check`, `calm-validate`) pass cleanly.
- [x] **Step 2: Update README and execution logs**
  Document metrics usage in `chapter06/kafka/README.md` and append phase logs to `chapter06/kafka/execution-v0.md` and `photoz/skills/execution-v0.md`.

