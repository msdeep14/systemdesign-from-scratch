"""Kafka Consumer daemon for Notification events."""

from bses.kafka import BaseKafkaConsumerCommand
from notifications.services import bulk_create_notifications


class Command(BaseKafkaConsumerCommand):
    """Consumer command that pulls Notification events and persists Notification records."""

    help = "Runs the Kafka Consumer Daemon for Notifications"
    topic_key = "notifications"
    group_id = "photoz-notifications-group"
    batch_size = 500

    def handle_payloads(self, payloads: list[dict]) -> int:
        """Process notification events in batch."""
        count = bulk_create_notifications(payloads)
        self.stdout.write(self.style.SUCCESS(f"Successfully processed {count} records."))
        return count

    def persist_records(self, records: list[tuple[int, int]]) -> int:
        """Unused as handle_payloads is overridden for dictionary events."""
        return 0
