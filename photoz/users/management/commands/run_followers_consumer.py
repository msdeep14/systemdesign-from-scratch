"""Kafka Consumer daemon for Follow events."""

from bses.kafka_consumer import BaseKafkaConsumerCommand
from users.services import bulk_record_follows


class Command(BaseKafkaConsumerCommand):
    """Consumer command that pulls Follow events in batches and persists them."""

    help = "Runs the Kafka Consumer Daemon for Follows (Batching via Pull Model)"
    topic_key = "follows"
    group_id = "photoz-follows-group"
    payload_key_1 = "follower_id"
    payload_key_2 = "following_id"

    def persist_records(self, records: list[tuple[int, int]]) -> int:
        """Bulk insert Follow records with updated follower counts."""
        return bulk_record_follows(records)
