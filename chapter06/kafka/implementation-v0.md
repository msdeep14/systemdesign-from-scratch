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
