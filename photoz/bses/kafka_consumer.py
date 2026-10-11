"""Base class for Kafka consumer management commands."""

import json
import os

from confluent_kafka import Consumer, KafkaError
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError


class BaseKafkaConsumerCommand(BaseCommand):
    """Abstract base command providing connection, consume loop, and batch persistence logic."""

    topic_key: str = ""
    group_id: str = ""
    batch_size: int = 5000
    poll_timeout: float = 1.0
    payload_key_1: str = ""
    payload_key_2: str = ""

    def handle(self, *args, **options) -> None:
        """Initialize Kafka consumer and enter processing loop."""
        bootstrap_servers = getattr(
            settings,
            "KAFKA_BOOTSTRAP_SERVERS",
            os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        )
        self.stdout.write(f"Connecting to Kafka at {bootstrap_servers}")

        conf = {
            "bootstrap.servers": bootstrap_servers,
            "group.id": self.group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }

        topic_name = settings.KAFKA_TOPICS.get(self.topic_key, {}).get("name", "")
        if not topic_name:
            self.stderr.write(f"No topic configuration found for '{self.topic_key}'")
            return

        consumer = Consumer(conf)
        consumer.subscribe([topic_name])
        self.stdout.write(f"Started listening to {topic_name}...")

        try:
            self._consume_loop(consumer)
        except KeyboardInterrupt:
            self.stdout.write("Shutting down consumer...")
        finally:
            consumer.close()

    def _extract_payloads(self, msgs: list) -> list[dict]:
        """Extract valid JSON dict payloads from Kafka messages.

        Skips partition EOF and invalid records.
        """
        payloads: list[dict] = []
        for msg in msgs:
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    self.stderr.write(f"Kafka Error: {msg.error()}")
                continue

            try:
                payload = json.loads(msg.value().decode("utf-8"))
                payloads.append(payload)
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                self.stderr.write(f"Failed to parse message: {err}")

        return payloads

    def _consume_loop(self, consumer: Consumer) -> None:
        """Poll batches and commit offsets upon successful persistence."""
        while True:
            msgs = consumer.consume(num_messages=self.batch_size, timeout=self.poll_timeout)
            if not msgs:
                continue

            payloads = self._extract_payloads(msgs)
            if not payloads:
                consumer.commit()
                continue

            try:
                self.handle_payloads(payloads)
                consumer.commit()
            except DatabaseError as err:
                self.stderr.write(f"Database error during persistence: {err}")

    def handle_payloads(self, payloads: list[dict]) -> None:
        """Extract configured key pairs and invoke persistence handler."""
        pairs = [
            (p[self.payload_key_1], p[self.payload_key_2])
            for p in payloads
            if self.payload_key_1 in p and self.payload_key_2 in p
        ]
        if pairs:
            count = self.persist_records(pairs)
            self.stdout.write(self.style.SUCCESS(f"Successfully processed {count} records."))

    def persist_records(self, records: list[tuple[int, int]]) -> int:
        """Persist a batch of records. Subclasses must implement this method."""
        raise NotImplementedError("Subclasses must implement persist_records()")
