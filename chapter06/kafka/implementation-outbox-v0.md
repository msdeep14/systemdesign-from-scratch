# Outbox Pattern — Photoz Implementation Plan

**Scope**: Prevent silent Kafka event loss when a process crashes between a DB write and `publish_kafka_event`.

---

## Problem

8 call sites in Photoz do:
```python
model.save()              # DB write
publish_kafka_event(...)  # separate Kafka write — can be lost on crash
```

**Apply outbox to**: `uploads`, `deletions`, `follows`, all `notifications`.  
**Skip**: `likes` — Redis already holds live state, DB persistence is best-effort.

---

## New Files

### `bses/outbox.py`
```python
from django.db import models


class OutboxEvent(models.Model):
    topic_key = models.CharField(max_length=100)
    payload = models.JSONField()
    partition_key = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published = models.BooleanField(default=False, db_index=True)

    class Meta:
        app_label = "bses"
        indexes = [
            models.Index(fields=["published", "created_at"]),
        ]
```

### `bses/management/commands/run_outbox_relay.py`
```python
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from bses.kafka import publish_kafka_event
from bses.outbox import OutboxEvent

logger = logging.getLogger("bses")

POLL_INTERVAL = int(getattr(settings, "OUTBOX_RELAY_POLL_INTERVAL", 5))
BATCH_SIZE = int(getattr(settings, "OUTBOX_RELAY_BATCH_SIZE", 500))


class Command(BaseCommand):
    help = "Outbox relay: publishes pending OutboxEvent rows to Kafka."

    def handle(self, *args, **options):
        self.stdout.write("Starting outbox relay...")
        while True:
            self._process_batch()
            time.sleep(POLL_INTERVAL)

    def _process_batch(self):
        # Use select_for_update(skip_locked=True) if running on multiple nodes
        batch = list(
            OutboxEvent.objects.filter(published=False)
            .order_by("created_at")[:BATCH_SIZE]
        )
        if not batch:
            return

        published_ids = []
        for event in batch:
            success = publish_kafka_event(
                event.topic_key,
                event.payload,
                key=event.partition_key or None,
            )
            if success:
                published_ids.append(event.id)
            else:
                logger.error("Failed to publish outbox event id=%s topic=%s", event.id, event.topic_key)

        if published_ids:
            OutboxEvent.objects.filter(id__in=published_ids).update(published=True)
            self.stdout.write(f"Published {len(published_ids)} outbox events.")
```

---

## Changes to Existing Files

### `bses/kafka.py` — add helper (publish_kafka_event unchanged)
```python
def queue_kafka_event(topic_key: str, payload: dict, partition_key: str = "") -> None:
    """Write outbox event in the current DB transaction. Call alongside primary DB write."""
    from bses.outbox import OutboxEvent
    OutboxEvent.objects.create(
        topic_key=topic_key,
        payload=payload,
        partition_key=partition_key,
    )
```

### `photos/views.py` — upload_photo
```diff
- photo.save()
- publish_kafka_event("uploads", {"photo_id": photo.id, "user_id": request.user.id}, key=str(request.user.id))
+ with transaction.atomic():
+     photo.save()
+     queue_kafka_event("uploads", {"photo_id": photo.id, "user_id": request.user.id}, partition_key=str(request.user.id))
```

### `photos/views.py` — delete_photo
Write to outbox before deletion; remove `photo_deleted.send(...)`.
```diff
+ with transaction.atomic():
+     queue_kafka_event("deletions", {"user_id": request.user.id, "photo_id": photo.id}, partition_key=str(request.user.id))
+     photo.delete()
- photo.delete()
- photo_deleted.send(sender=Photo, user=request.user)
```

### `users/views.py` — toggle_follow_view (follow branch)
```diff
- publish_kafka_event("follows", {"follower_id": request.user.id, "following_id": target_user.id}, key=str(target_user.id))
+ with transaction.atomic():
+     Follow.objects.create(follower=request.user, following=target_user)
+     queue_kafka_event("follows", {"follower_id": request.user.id, "following_id": target_user.id}, partition_key=str(target_user.id))
```

### `notifications/signals.py` — all 5 handlers
Replace `publish_kafka_event` with `queue_kafka_event` and `key=` with `partition_key=` in handlers:
`_handle_photo_liked`, `_handle_photo_commented`, `_handle_member_invited`, `_handle_user_tagged`, `_handle_story_user_tagged`.

### `newsfeed/signals.py`
Remove `_handle_photo_deleted` — outbox in the view replaces it.

---

## Settings additions (`bses/settings.py`)
```python
OUTBOX_RELAY_POLL_INTERVAL = int(os.environ.get("OUTBOX_RELAY_POLL_INTERVAL", "5"))
OUTBOX_RELAY_BATCH_SIZE = int(os.environ.get("OUTBOX_RELAY_BATCH_SIZE", "500"))
```

## docker-compose.yml — new service
```yaml
  outbox-relay:
    build: .
    restart: always
    command: python manage.py run_outbox_relay
    env_file:
      - .env
    environment:
      - POSTGRES_HOST=pgbouncer
      - POSTGRES_PORT=6432
      - REDIS_URL=redis://redis:6379/1
      - KAFKA_BOOTSTRAP_SERVERS=kafka:29092
    depends_on:
      - db
      - pgbouncer
      - kafka
```

---

## File Change Summary

| File | Type |
|---|---|
| `bses/outbox.py` | New |
| `bses/migrations/XXXX_outboxevent.py` | New (makemigrations bses) |
| `bses/management/commands/run_outbox_relay.py` | New |
| `bses/kafka.py` | Add `queue_kafka_event` |
| `bses/settings.py` | Add 2 settings |
| `photos/views.py` | Modify upload + delete |
| `users/views.py` | Modify follow branch |
| `notifications/signals.py` | Replace publish with queue in 5 handlers |
| `newsfeed/signals.py` | Remove `_handle_photo_deleted` |
| `docker-compose.yml` | Add `outbox-relay` service |
