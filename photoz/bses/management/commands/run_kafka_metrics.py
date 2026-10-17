"""Django management command running Kafka queue and lag metrics daemon."""

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from bses.kafka_metrics import collect_all_kafka_metrics, emit_kafka_metrics


class Command(BaseCommand):
    """Periodically queries Kafka topic watermarks and consumer offsets, emitting CloudWatch EMF."""

    help = "Periodically collects and emits Kafka queue backlog and lag metrics to CloudWatch EMF."

    def add_arguments(self, parser):
        """Register CLI flags."""
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run collection cycle once and exit immediately.",
        )

    def handle(self, *args, **options):
        """Execute single collection or enter continuous daemon loop."""
        interval = getattr(settings, "KAFKA_METRICS_INTERVAL_SECONDS", 60)
        if options.get("once"):
            payloads = collect_all_kafka_metrics()
            emit_kafka_metrics(payloads)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully emitted metrics for {len(payloads)} topic and DLQ streams."
                )
            )
            return

        self.stdout.write(f"Starting Kafka metrics daemon (interval: {interval}s)...")
        try:
            while True:
                payloads = collect_all_kafka_metrics()
                emit_kafka_metrics(payloads)
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("Shutting down Kafka metrics daemon...")
            return
