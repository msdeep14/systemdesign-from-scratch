"""Unit tests for the run_kafka_metrics management command."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class RunKafkaMetricsCommandTests(SimpleTestCase):
    """Test suite for run_kafka_metrics management command."""

    @patch("bses.management.commands.run_kafka_metrics.emit_kafka_metrics")
    @patch("bses.management.commands.run_kafka_metrics.collect_all_kafka_metrics")
    def test_run_kafka_metrics_once(self, mock_collect, mock_emit):
        """Verify command runs single iteration and exits when --once is provided."""
        mock_collect.return_value = [
            {"Topic": "photo.events.likes", "ConsumerLag": 10},
            {"Topic": "photo.events.uploads", "ConsumerLag": 0},
        ]

        out = StringIO()
        call_command("run_kafka_metrics", once=True, stdout=out)

        mock_collect.assert_called_once()
        mock_emit.assert_called_once_with(mock_collect.return_value)
        output_str = out.getvalue()
        self.assertIn("Successfully emitted metrics for 2 topic and DLQ streams.", output_str)
        self.assertNotIn("Failed", output_str)
        self.assertFalse("error" in output_str.lower())
        self.assertNotEqual(len(output_str), 0)
