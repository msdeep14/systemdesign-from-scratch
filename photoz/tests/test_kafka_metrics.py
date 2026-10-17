"""Unit tests for Kafka queue and lag metrics computation and CloudWatch EMF formatting."""

import json
from unittest.mock import MagicMock

from confluent_kafka import OFFSET_INVALID, TopicPartition
from django.test import SimpleTestCase

from bses.kafka_metrics import (
    compute_dlq_metrics,
    compute_topic_metrics,
    format_emf_payload,
)


class KafkaMetricsTests(SimpleTestCase):
    """Test suite for Kafka metrics calculation and CloudWatch EMF payload structure."""

    def test_format_emf_payload(self):
        """Verify EMF dictionary structure adheres to AWS CloudWatch EMF specification."""
        payload = format_emf_payload(
            namespace="PhotoZ/Kafka",
            dimensions=[["Topic", "ConsumerGroup"]],
            metrics=[
                {"Name": "ConsumerLag", "Unit": "Count"},
                {"Name": "TimeLagSeconds", "Unit": "Seconds"},
            ],
            properties={
                "Topic": "photo.events.likes",
                "ConsumerGroup": "photoz-likes-group",
                "ConsumerLag": 150,
                "TimeLagSeconds": 1.25,
            },
        )

        self.assertIn("_aws", payload)
        aws_block = payload["_aws"]
        self.assertIn("Timestamp", aws_block)
        self.assertEqual(len(aws_block["CloudWatchMetrics"]), 1)

        metric_def = aws_block["CloudWatchMetrics"][0]
        self.assertEqual(metric_def["Namespace"], "PhotoZ/Kafka")
        self.assertEqual(metric_def["Dimensions"], [["Topic", "ConsumerGroup"]])
        self.assertEqual(len(metric_def["Metrics"]), 2)

        self.assertEqual(payload["Topic"], "photo.events.likes")
        self.assertEqual(payload["ConsumerGroup"], "photoz-likes-group")
        self.assertEqual(payload["ConsumerLag"], 150)
        self.assertEqual(payload["TimeLagSeconds"], 1.25)
        self.assertNotIn("UnknownProperty", payload)
        self.assertNotEqual(payload["ConsumerLag"], 0)

        serialized = json.dumps(payload)
        self.assertIn("PhotoZ/Kafka", serialized)
        self.assertNotIn("None", serialized)

    def test_compute_topic_metrics_normal_lag(self):
        """Verify topic metrics computation with healthy committed offsets."""
        mock_consumer = MagicMock()

        def mock_watermarks(tp, timeout=5):
            if tp.partition == 0:
                return (0, 100)
            return (0, 200)

        def mock_committed(partitions, timeout=5):
            results = []
            for tp in partitions:
                offset = 80 if tp.partition == 0 else 150
                results.append(TopicPartition(tp.topic, tp.partition, offset))
            return results

        mock_consumer.get_watermark_offsets.side_effect = mock_watermarks
        mock_consumer.committed.side_effect = mock_committed

        metrics = compute_topic_metrics(
            topic_name="photo.events.likes",
            consumer_group="photoz-likes-group",
            num_partitions=2,
            consumer=mock_consumer,
            fetch_timestamp=False,
        )

        self.assertEqual(metrics["Topic"], "photo.events.likes")
        self.assertEqual(metrics["ConsumerGroup"], "photoz-likes-group")
        self.assertEqual(metrics["ConsumerLag"], 70)
        self.assertEqual(metrics["MaxPartitionLag"], 50)
        self.assertEqual(metrics["LogEndOffset"], 300)
        self.assertEqual(metrics["TimeLagSeconds"], 0.0)
        self.assertFalse(metrics["ConsumerLag"] < 0)
        self.assertFalse(metrics["MaxPartitionLag"] > metrics["ConsumerLag"])
        self.assertNotEqual(metrics["ConsumerLag"], 0)

    def test_compute_topic_metrics_uncommitted_offsets(self):
        """Verify topic metrics computation when consumer group has not yet committed offsets."""
        mock_consumer = MagicMock()

        def mock_watermarks(tp, timeout=5):
            return (0, 50)

        def mock_committed(partitions, timeout=5):
            return [TopicPartition(tp.topic, tp.partition, OFFSET_INVALID) for tp in partitions]

        mock_consumer.get_watermark_offsets.side_effect = mock_watermarks
        mock_consumer.committed.side_effect = mock_committed

        metrics = compute_topic_metrics(
            topic_name="photo.events.uploads",
            consumer_group="photoz-uploads-group",
            num_partitions=2,
            consumer=mock_consumer,
            fetch_timestamp=False,
        )

        self.assertEqual(metrics["ConsumerLag"], 100)
        self.assertEqual(metrics["MaxPartitionLag"], 50)
        self.assertEqual(metrics["LogEndOffset"], 100)
        self.assertFalse(metrics["ConsumerLag"] < 0)
        self.assertNotEqual(metrics["ConsumerLag"], 0)
        self.assertNotIn("UnknownKey", metrics)

    def test_compute_dlq_metrics(self):
        """Verify dead-letter queue depth calculation across all partitions."""
        mock_consumer = MagicMock()

        def mock_watermarks(tp, timeout=5):
            return (0, 5)

        mock_consumer.get_watermark_offsets.side_effect = mock_watermarks

        metrics = compute_dlq_metrics(
            dlq_topic_name="photo.events.likes.dlq",
            num_partitions=3,
            consumer=mock_consumer,
        )

        self.assertEqual(metrics["Topic"], "photo.events.likes.dlq")
        self.assertEqual(metrics["DLQDepth"], 15)
        self.assertFalse(metrics["DLQDepth"] < 0)
        self.assertNotEqual(metrics["DLQDepth"], 0)
