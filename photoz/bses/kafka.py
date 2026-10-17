"""Kafka infrastructure utilities for Photoz (Producers, Consumers, and DLQ)."""

import json
import logging
import os
import time
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


def publish_to_dlq(
    topic_key: str,
    payload: Any,
    error: Exception | str,
    key: str | None = None,
    retry_count: int = 0,
) -> bool:
    """Publish a failed or poison-pill message to the corresponding DLQ topic.

    Args:
        topic_key: Key in settings.KAFKA_TOPICS (e.g., 'likes', 'follows', 'uploads').
        payload: Original message payload or raw string.
        error: Exception or string describing the failure.
        key: Optional partition key.
        retry_count: Number of retries attempted before DLQ routing.
    """
    topic_info = getattr(settings, "KAFKA_TOPICS", {}).get(topic_key)
    if not topic_info:
        logger.warning("Kafka topic key '%s' not found for DLQ routing", topic_key)
        return False

    dlq_topic_name = f"{topic_info.get('name', '')}.dlq"
    error_type = (
        error.__class__.__name__ if isinstance(error, Exception) else "DeserializationError"
    )
    envelope = {
        "original_topic": topic_info.get("name", ""),
        "original_payload": payload,
        "error_type": error_type,
        "error_message": str(error),
        "timestamp": time.time(),
        "retry_count": retry_count,
    }

    try:
        producer = get_kafka_producer()
        value_bytes = json.dumps(envelope).encode("utf-8")
        key_bytes = key.encode("utf-8") if key is not None else None

        producer.produce(
            topic=dlq_topic_name,
            value=value_bytes,
            key=key_bytes,
            on_delivery=_delivery_report,
        )
        producer.poll(0)
        return True
    except (KafkaException, BufferError, TypeError) as err:
        _log_publish_failure(dlq_topic_name, err)
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
    max_retries: int = 3
    retry_backoff_base: float = 0.5

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

        Skips partition EOF and routes corrupted records to DLQ.
        """
        payloads: list[dict] = []
        for msg in msgs:
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    self.stderr.write(f"Kafka Error: {msg.error()}")
                continue

            payload = _safe_deserialize(msg.value())
            if payload is None:
                raw_str = msg.value().decode("utf-8", errors="replace") if msg.value() else ""
                publish_to_dlq(self.topic_key, raw_str, "JSON deserialization error")
                self.stderr.write(f"Routed corrupted message to DLQ: {raw_str[:50]}")
                continue

            payloads.append(payload)

        return payloads

    def _compute_batch_timelag(self, msgs: list) -> float:
        """Calculate processing delay in seconds from newest record timestamp in batch."""
        newest_ts = 0
        for msg in msgs:
            _ts_type, ts_val = msg.timestamp()
            newest_ts = max(newest_ts, ts_val)

        if newest_ts > 0:
            return round(max(0.0, time.time() - (newest_ts / 1000.0)), 2)
        return 0.0

    def _emit_consumer_metrics(self, batch_size: int, time_lag: float) -> None:
        """Emit CloudWatch EMF metrics for consumer batch commit."""
        topic_name = settings.KAFKA_TOPICS.get(self.topic_key, {}).get("name", self.topic_key)
        emf_payload = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "PhotoZ/Kafka",
                        "Dimensions": [["Topic", "ConsumerGroup"]],
                        "Metrics": [
                            {"Name": "TimeLagSeconds", "Unit": "Seconds"},
                            {"Name": "BatchRecordsProcessed", "Unit": "Count"},
                        ],
                    }
                ],
            },
            "Topic": topic_name,
            "ConsumerGroup": self.group_id,
            "TimeLagSeconds": time_lag,
            "BatchRecordsProcessed": batch_size,
        }
        metrics_logger = logging.getLogger("metrics")
        metrics_logger.info(json.dumps(emf_payload))

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

            time_lag = self._compute_batch_timelag(msgs)
            self.handle_payloads(payloads)
            consumer.commit()
            self._emit_consumer_metrics(len(payloads), time_lag)

    def _handle_record_failure(self, pair: tuple[int, int], err: Exception) -> None:
        """Route failed record to DLQ and log to stderr."""
        publish_to_dlq(
            self.topic_key,
            {self.payload_key_1: pair[0], self.payload_key_2: pair[1]},
            err,
            key=str(pair[0]),
        )
        self.stderr.write(f"Skipping invalid record {pair} (routed to DLQ): {err}")

    def _persist_single(self, pair: tuple[int, int]) -> int:
        """Persist a single record, logging and routing to DLQ on failure."""
        try:
            return self.persist_records([pair])
        except (IntegrityError, DatabaseError) as err:
            self._handle_record_failure(pair, err)
            return 0

    def _fallback_persist(self, pairs: list[tuple[int, int]]) -> int:
        """Persist records individually when batch insertion fails."""
        successful = sum(self._persist_single(pair) for pair in pairs)
        self.stdout.write(self.style.SUCCESS(f"Successfully processed {successful} valid records."))
        return successful

    def _handle_batch_retry(
        self, pairs: list[tuple[int, int]], err: Exception, attempt: int
    ) -> int | None:
        """Handle batch error, falling back if unrecoverable or sleeping for retry."""
        if isinstance(err, IntegrityError) or attempt >= self.max_retries - 1:
            self.stderr.write(f"Batch persistence failed: {err}")
            return self._fallback_persist(pairs)

        backoff = self.retry_backoff_base * (2**attempt)
        self.stderr.write(
            f"Transient database error (attempt {attempt + 1}/{self.max_retries}): {err}. "
            f"Retrying in {backoff:.1f}s..."
        )
        time.sleep(backoff)
        return None

    def _persist_batch_attempt(self, pairs: list[tuple[int, int]], attempt: int) -> int | None:
        """Execute single batch attempt, returning count or None if retrying."""
        try:
            return self.persist_records(pairs)
        except (IntegrityError, DatabaseError) as err:
            self.stderr.write(f"Database error on batch attempt {attempt + 1}: {err}")
            return self._handle_batch_retry(pairs, err, attempt)

    def _persist_batch_with_retry(self, pairs: list[tuple[int, int]]) -> int:
        """Attempt batch insertion with retries for transient errors."""
        for attempt in range(self.max_retries):
            result = self._persist_batch_attempt(pairs, attempt)
            if result is not None:
                return result
        return self._fallback_persist(pairs)

    def handle_payloads(self, payloads: list[dict]) -> int:
        """Extract configured key pairs and invoke persistence handler."""
        pairs: list[tuple[int, int]] = []
        for p in payloads:
            if self.payload_key_1 in p and self.payload_key_2 in p:
                pairs.append((p[self.payload_key_1], p[self.payload_key_2]))
            else:
                publish_to_dlq(
                    self.topic_key,
                    p,
                    f"Missing required keys '{self.payload_key_1}' or '{self.payload_key_2}'",
                )
                self.stderr.write(f"Routed malformed payload to DLQ: {p}")

        if not pairs:
            return 0

        count = self._persist_batch_with_retry(pairs)
        self.stdout.write(self.style.SUCCESS(f"Successfully processed {count} records."))
        return count

    @abstractmethod
    def persist_records(self, records: list[tuple[int, int]]) -> int:
        """Persist a batch of records. Subclasses must implement this method."""
        raise NotImplementedError("Subclasses must implement persist_records()")
