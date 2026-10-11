# Phase 5: Dead Letter Queue (DLQ) & Retry Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement fault-tolerant error handling across all Photoz Kafka consumers by adding transient error retries with exponential backoff and routing permanent poison pills / deserialization errors to dedicated Dead Letter Queue (DLQ) topics.

**Architecture:** Extend `BaseKafkaConsumerCommand` and `bses.kafka` with a structured `publish_to_dlq` utility. When consumers encounter unparseable JSON, malformed schemas, or database integrity failures (e.g., missing foreign keys), wrap the failed payload with diagnostic error metadata, publish to `{topic}.dlq`, and commit the primary partition offset so the consumer group never deadlocks.

**Tech Stack:** Python 3.12, confluent-kafka, Django 5.0, PostgreSQL, Apache Kafka 4.3.1 (KRaft).

**Spec:** Chapter 6 Asynchronous Processing Architecture - Phase 5 DLQ & Retry Policy.

## Global Constraints
- Code changes must adhere to the modular monolith boundaries enforced by `import-linter`.
- Pylint rating must remain at 10.00/10.
- All `try/except` blocks in `bses/kafka.py` must conform to the canonical `[call, return]` pattern to avoid `pattern_fragmentation` drift findings.
- No auto-commit. The user will review and commit manually.
- Plain English documentation and logs only; no emojis.

---

### Task 1: DLQ Publishing Utility
**Files:**
- Modify: `photoz/bses/kafka.py`

**Interfaces:**
- Produces: `publish_to_dlq(topic_key: str, payload: Any, error: Exception | str, key: str | None = None, retry_count: int = 0) -> bool`

- [x] **Step 1: Implement `publish_to_dlq`**
  Add `publish_to_dlq` to `photoz/bses/kafka.py` wrapping failed payloads in a diagnostic envelope containing `original_topic`, `original_payload`, `error_type`, `error_message`, `timestamp`, and `retry_count`.
- [x] **Step 2: Ensure standardized error handling**
  Use `_log_publish_failure(dlq_topic_name, err)` in the except handler to match canonical `[call, return]` pattern.

---

### Task 2: Consumer Retry Policy with Exponential Backoff
**Files:**
- Modify: `photoz/bses/kafka.py`

**Interfaces:**
- Consumes: `settings.KAFKA_TOPICS`, `publish_to_dlq`
- Modifies: `BaseKafkaConsumerCommand`

- [x] **Step 1: Add retry configuration attributes**
  Add `max_retries: int = 3` and `retry_backoff_base: float = 0.5` to `BaseKafkaConsumerCommand`.
- [x] **Step 2: Implement transient retry handling**
  In `BaseKafkaConsumerCommand`, add exponential backoff retry for transient database errors prior to falling back to individual persistence.

---

### Task 3: DLQ Routing for Deserialization Errors & Poison Pills
**Files:**
- Modify: `photoz/bses/kafka.py`

**Interfaces:**
- Modifies: `BaseKafkaConsumerCommand._extract_payloads`, `BaseKafkaConsumerCommand._persist_single`, `BaseKafkaConsumerCommand.handle_payloads`

- [x] **Step 1: Route deserialization errors to DLQ**
  Update `_extract_payloads` so messages failing `_safe_deserialize` are published to the topic's DLQ instead of being silently dropped.
- [x] **Step 2: Route poison pills to DLQ in `_persist_single`**
  When a record fails with `IntegrityError` (foreign key violations) or unrecoverable `DatabaseError`, publish to DLQ with error diagnostics and commit offset.
- [x] **Step 3: Route schema violations to DLQ in `handle_payloads`**
  When a payload is missing required keys, route to DLQ with schema violation error.

---

### Task 4: End-to-End Verification & Pre-Commit Validation
**Files:**
- Test against running Kafka cluster: `photo.events.likes.dlq`, `photo.events.uploads.dlq`, `photo.events.follows.dlq`.

- [x] **Step 1: Test corrupted JSON routing to DLQ**
  Publish an invalid non-JSON string to `photo.events.likes` and verify it routes to `photo.events.likes.dlq`.
- [x] **Step 2: Test foreign key poison pill routing to DLQ**
  Publish an event with non-existent user/photo IDs and verify it is captured in `photo.events.likes.dlq`.
- [x] **Step 3: Run all 6 pre-commit hooks**
  Run `ruff`, `ruff-format`, `pylint`, `import-linter`, `drift-check`, and `calm-validate`.

---

### Task 5: Documentation & Execution Logging
**Files:**
- Modify: `chapter06/kafka/README.md`
- Modify: `chapter06/kafka/execution-v0.md`
- Modify: `photoz/skills/execution-v0.md`

- [x] **Step 1: Update README.md**
  Add instructions for inspecting DLQ topics using `kafka-console-consumer.sh` and configuring retry settings.
- [x] **Step 2: Update execution logs**
  Log technical analysis, actions taken, and verification results in both execution log files.
