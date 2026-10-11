"""Kafka Consumer daemon for Like events."""

from bses.kafka import BaseKafkaConsumerCommand
from photos.services import bulk_record_likes


class Command(BaseKafkaConsumerCommand):
    """Consumer command that pulls Like events in batches and persists them."""

    help = "Runs the Kafka Consumer Daemon for Likes (Batching via Pull Model)"
    topic_key = "likes"
    group_id = "photoz-likes-group"
    payload_key_1 = "photo_id"
    payload_key_2 = "user_id"

    def persist_records(self, records: list[tuple[int, int]]) -> int:
        """Bulk insert Like records into PostgreSQL."""
        return bulk_record_likes(records)
