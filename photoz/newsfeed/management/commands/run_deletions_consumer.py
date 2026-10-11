"""Kafka Consumer daemon for Photo Deletion events."""

from bses.kafka import BaseKafkaConsumerCommand
from newsfeed.services import bulk_invalidate_follower_feed_caches


class Command(BaseKafkaConsumerCommand):
    """Consumer command that pulls Deletion events and invalidates followers' newsfeed caches."""

    help = "Runs the Kafka Consumer Daemon for Photo Deletions (Newsfeed Invalidation)"
    topic_key = "deletions"
    group_id = "photoz-deletions-group"
    batch_size = 100
    payload_key_1 = "user_id"
    payload_key_2 = "photo_id"

    def persist_records(self, records: list[tuple[int, int]]) -> int:
        """Invalidate follower feed caches in Redis."""
        return bulk_invalidate_follower_feed_caches(records)
