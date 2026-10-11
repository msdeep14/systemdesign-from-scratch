"""Kafka Consumer daemon for Photo Upload events."""

from bses.kafka import BaseKafkaConsumerCommand
from newsfeed.services import bulk_fanout_photo_uploads


class Command(BaseKafkaConsumerCommand):
    """Consumer command that pulls Upload events in batches and executes newsfeed fanout."""

    help = "Runs the Kafka Consumer Daemon for Photo Uploads (Newsfeed Fanout)"
    topic_key = "uploads"
    group_id = "photoz-uploads-group"
    batch_size = 100
    payload_key_1 = "user_id"
    payload_key_2 = "photo_id"

    def persist_records(self, records: list[tuple[int, int]]) -> int:
        """Fan out uploaded photos to uploader and follower feeds."""
        return bulk_fanout_photo_uploads(records)
