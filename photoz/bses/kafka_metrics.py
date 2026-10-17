"""Kafka queue and lag metrics collector for CloudWatch Embedded Metric Format (EMF)."""

import json
import logging
import os
import time
from typing import Any

from confluent_kafka import OFFSET_INVALID, Consumer, KafkaException, TopicPartition
from django.conf import settings

logger = logging.getLogger("metrics")

DEFAULT_CONSUMER_GROUPS = {
    "photo.events.likes": "photoz-likes-group",
    "photo.events.uploads": "photoz-uploads-group",
    "photo.events.follows": "photoz-followers-group",
    "photo.events.notifications": "photoz-notifications-group",
    "photo.events.deletions": "photoz-deletions-group",
}


def format_emf_payload(
    namespace: str,
    dimensions: list[list[str]],
    metrics: list[dict[str, str]],
    properties: dict[str, Any],
) -> dict[str, Any]:
    """Format dictionary payload according to CloudWatch Embedded Metric Format (EMF) spec."""
    payload = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": namespace,
                    "Dimensions": dimensions,
                    "Metrics": metrics,
                }
            ],
        }
    }
    payload.update(properties)
    return payload


def _poll_partition_timestamp(consumer: Any, tp: TopicPartition) -> float | None:
    """Assign partition, poll message timestamp, and unassign safely."""
    try:
        consumer.assign([tp])
        msg = consumer.poll(timeout=0.3)
        consumer.unassign()
        if msg and not msg.error():
            _ts_type, ts_val = msg.timestamp()
            if ts_val > 0:
                return ts_val / 1000.0
        return None
    except KafkaException as err:
        logger.debug("Failed to read timestamp from %s: %s", tp, err)
        return None


def _get_oldest_unread_timestamp(
    consumer: Any, topic: str, partition: int, offset: int
) -> float | None:
    """Inspect message timestamp at given partition offset without committing."""
    return _poll_partition_timestamp(consumer, TopicPartition(topic, partition, offset))


def _query_watermarks(consumer: Any, tp: TopicPartition) -> tuple[int, int]:
    """Query low and high watermarks for a partition safely."""
    try:
        return consumer.get_watermark_offsets(tp, timeout=5)
    except KafkaException as err:
        logger.debug("Failed to query watermarks for %s: %s", tp, err)
        return (0, 0)


def _query_committed(consumer: Any, partitions: list[TopicPartition]) -> list[TopicPartition]:
    """Query committed offsets for partitions safely."""
    try:
        return consumer.committed(partitions, timeout=5)
    except KafkaException as err:
        logger.debug("Failed to query committed offsets: %s", err)
        return []


def _compute_partition_lags(
    consumer: Any,
    topic_name: str,
    num_partitions: int,
) -> tuple[list[int], list[int], tuple[int, int] | None]:
    """Calculate per-partition lags, high watermarks, and find the first stalled offset."""
    partitions_to_query = [TopicPartition(topic_name, p) for p in range(num_partitions)]
    committed_offsets = _query_committed(consumer, partitions_to_query)
    committed_map = {tp.partition: tp.offset for tp in committed_offsets}

    lags: list[int] = []
    highs: list[int] = []
    stalled_offset: tuple[int, int] | None = None

    for p in range(num_partitions):
        low, high = _query_watermarks(consumer, TopicPartition(topic_name, p))
        highs.append(high)

        offset = committed_map.get(p, OFFSET_INVALID)
        effective = low if (offset is None or offset < 0) else offset
        lag = max(0, high - effective)
        lags.append(lag)

        if lag > 0 and stalled_offset is None:
            stalled_offset = (p, effective)

    return lags, highs, stalled_offset


def compute_topic_metrics(
    topic_name: str,
    consumer_group: str,
    num_partitions: int,
    consumer: Any,
    fetch_timestamp: bool = True,
) -> dict[str, Any]:
    """Calculate aggregated queue backlog, partition skew, and message time lag for a topic."""
    partition_lags, high_watermarks, oldest_stalled = _compute_partition_lags(
        consumer, topic_name, num_partitions
    )
    consumer_lag = sum(partition_lags)
    time_lag_seconds = 0.0

    if consumer_lag > 0 and fetch_timestamp and oldest_stalled:
        stalled_ts = _get_oldest_unread_timestamp(
            consumer, topic_name, oldest_stalled[0], oldest_stalled[1]
        )
        if stalled_ts is not None:
            time_lag_seconds = round(max(0.0, time.time() - stalled_ts), 2)

    return {
        "Topic": topic_name,
        "ConsumerGroup": consumer_group,
        "ConsumerLag": consumer_lag,
        "MaxPartitionLag": max(partition_lags) if partition_lags else 0,
        "LogEndOffset": sum(high_watermarks),
        "TimeLagSeconds": time_lag_seconds,
    }


def compute_dlq_metrics(
    dlq_topic_name: str,
    num_partitions: int,
    consumer: Any,
) -> dict[str, Any]:
    """Calculate total unhandled dead-letter queue records across all partitions."""
    depths: list[int] = []
    for p in range(num_partitions):
        low, high = _query_watermarks(consumer, TopicPartition(dlq_topic_name, p))
        depths.append(max(0, high - low))

    return {
        "Topic": dlq_topic_name,
        "DLQDepth": sum(depths),
    }


def _collect_single_topic_metrics(
    topic_key: str,
    topic_info: dict[str, Any],
    consumer: Any,
    fetch_timestamp: bool,
) -> list[dict[str, Any]]:
    """Generate EMF payloads for a configured topic and its DLQ counterpart."""
    topic_name = topic_info.get("name", "")
    if not topic_name:
        return []

    fallback_group = DEFAULT_CONSUMER_GROUPS.get(topic_name, f"photoz-{topic_key}-group")
    consumer_group = topic_info.get("consumer_group", fallback_group)
    partitions = topic_info.get("partitions", 50)

    topic_stats = compute_topic_metrics(
        topic_name=topic_name,
        consumer_group=consumer_group,
        num_partitions=partitions,
        consumer=consumer,
        fetch_timestamp=fetch_timestamp,
    )
    payloads = [
        format_emf_payload(
            namespace="PhotoZ/Kafka",
            dimensions=[["Topic", "ConsumerGroup"]],
            metrics=[
                {"Name": "ConsumerLag", "Unit": "Count"},
                {"Name": "MaxPartitionLag", "Unit": "Count"},
                {"Name": "LogEndOffset", "Unit": "Count"},
                {"Name": "TimeLagSeconds", "Unit": "Seconds"},
            ],
            properties=topic_stats,
        )
    ]

    if topic_info.get("dlq", False):
        dlq_name = topic_info.get("dlq_name", f"{topic_name}.dlq")
        dlq_stats = compute_dlq_metrics(dlq_name, partitions, consumer)
        payloads.append(
            format_emf_payload(
                namespace="PhotoZ/Kafka",
                dimensions=[["Topic"]],
                metrics=[{"Name": "DLQDepth", "Unit": "Count"}],
                properties=dlq_stats,
            )
        )

    return payloads


def _close_consumer_and_log(consumer: Any, err: Exception) -> None:
    """Log error and close consumer on failure."""
    logger.error("Failed during Kafka metrics collection: %s", err)
    consumer.close()


def collect_all_kafka_metrics(
    bootstrap_servers: str | None = None, fetch_timestamp: bool = True
) -> list[dict[str, Any]]:
    """Query cluster metrics across all configured topics and produce CloudWatch EMF payloads."""
    servers = bootstrap_servers or getattr(
        settings,
        "KAFKA_BOOTSTRAP_SERVERS",
        os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
    )
    conf = {
        "bootstrap.servers": servers,
        "group.id": "photoz-metrics-collector",
        "enable.auto.commit": False,
    }

    try:
        consumer = Consumer(conf)
    except KafkaException as err:
        logger.error("Failed to initialize Kafka metrics consumer: %s", err)
        return []

    emf_payloads: list[dict[str, Any]] = []
    topics_config = getattr(settings, "KAFKA_TOPICS", {})
    try:
        for topic_key, topic_info in topics_config.items():
            emf_payloads.extend(
                _collect_single_topic_metrics(topic_key, topic_info, consumer, fetch_timestamp)
            )
        consumer.close()
        return emf_payloads
    except KafkaException as err:
        _close_consumer_and_log(consumer, err)
        return []


def emit_kafka_metrics(payloads: list[dict[str, Any]]) -> None:
    """Serialize and log EMF payloads to the metrics console logger."""
    for payload in payloads:
        logger.info(json.dumps(payload))
