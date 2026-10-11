"""Kafka infrastructure utilities for Photoz (Producers and Consumers)."""

import json
import logging
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError, IntegrityError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_kafka_producer() -> Producer:
    """Return a process-wide singleton Kafka Producer instance."""
    bootstrap_servers = getattr(
        settings,
        "KAFKA_BOOTSTRAP_SERVERS",
        os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
    )
    conf = {
        "bootstrap.servers": bootstrap_servers,
        "client.id": "photoz-web-producer",
        "acks": 1,
    }
    return Producer(conf)


def _delivery_report(err: Any, msg: Any) -> None:
    """Callback for delivery reports from librdkafka."""
    if err is not None:
        logger.error("Failed to deliver Kafka message to %s: %s", msg.topic(), err)
    else:
        logger.debug("Kafka message delivered to %s [%s]", msg.topic(), msg.partition())


def _log_publish_failure(topic_name: str, err: Exception) -> None:
    """Log failure message when Kafka produce operation encounters an error."""
    logger.error("Failed to publish Kafka event to '%s': %s", topic_name, err)


def publish_kafka_event(topic_key: str, payload: dict[str, Any], key: str | None = None) -> bool:
    """Publish a JSON-serializable event dictionary to the configured Kafka topic.

    Args:
        topic_key: Key in settings.KAFKA_TOPICS (e.g., 'likes', 'follows', 'uploads').
        payload: Event payload dictionary to be JSON-encoded.
        key: Optional partition key to guarantee ordering per entity.
    """
    topic_info = getattr(settings, "KAFKA_TOPICS", {}).get(topic_key)
    if not topic_info:
        logger.warning("Kafka topic key '%s' not found in configuration", topic_key)
        return False

    topic_name = topic_info.get("name", "")
    try:
        producer = get_kafka_producer()
        value_bytes = json.dumps(payload).encode("utf-8")
        key_bytes = key.encode("utf-8") if key is not None else None

        producer.produce(
            topic=topic_name,
            value=value_bytes,
            key=key_bytes,
            on_delivery=_delivery_report,
        )
        producer.poll(0)
        return True
    except (KafkaException, BufferError, TypeError) as err:
        _log_publish_failure(topic_name, err)
        return False


def _safe_deserialize(raw_bytes: bytes) -> dict[str, Any] | None:
    """Deserialize UTF-8 JSON bytes into a dictionary, returning None on failure."""
    try:
        return json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        logger.debug("Failed to deserialize Kafka payload: %s", err)
        return None


class BaseKafkaConsumerCommand(BaseCommand, ABC):
    """Abstract base command providing connection, consume loop, and batch persistence logic."""

    topic_key: str = ""
    group_id: str = ""
    batch_size: int = 5000
    poll_timeout: float = 1.0
    payload_key_1: str = ""
    payload_key_2: str = ""

    def _shutdown(self, consumer: Consumer) -> None:
        """Close Kafka consumer during shutdown."""
        self.stdout.write("Shutting down consumer...")
        consumer.close()

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
            return None

        consumer = Consumer(conf)
        consumer.subscribe([topic_name])
        self.stdout.write(f"Started listening to {topic_name}...")

        try:
            return self._consume_loop(consumer)
        except KeyboardInterrupt:
            self._shutdown(consumer)
            return None

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

            payload = _safe_deserialize(msg.value())
            if payload is not None:
                payloads.append(payload)

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

            self.handle_payloads(payloads)
            consumer.commit()

    def _persist_single(self, pair: tuple[int, int]) -> int:
        """Persist a single record, logging and returning 0 on integrity error."""
        try:
            return self.persist_records([pair])
        except (IntegrityError, DatabaseError) as err:
            self.stderr.write(f"Skipping invalid record {pair}: {err}")
            return 0

    def _fallback_persist(self, pairs: list[tuple[int, int]]) -> int:
        """Persist records individually when batch insertion fails."""
        successful = sum(self._persist_single(pair) for pair in pairs)
        self.stdout.write(self.style.SUCCESS(f"Successfully processed {successful} valid records."))
        return successful

    def handle_payloads(self, payloads: list[dict]) -> int:
        """Extract configured key pairs and invoke persistence handler."""
        pairs = [
            (p[self.payload_key_1], p[self.payload_key_2])
            for p in payloads
            if self.payload_key_1 in p and self.payload_key_2 in p
        ]
        if not pairs:
            return 0

        try:
            count = self.persist_records(pairs)
            self.stdout.write(self.style.SUCCESS(f"Successfully processed {count} records."))
            return count
        except (IntegrityError, DatabaseError) as err:
            self.stderr.write(f"Database error during batch persistence: {err}")
            return self._fallback_persist(pairs)

    @abstractmethod
    def persist_records(self, records: list[tuple[int, int]]) -> int:
        """Persist a batch of records. Subclasses must implement this method."""
        raise NotImplementedError("Subclasses must implement persist_records()")
