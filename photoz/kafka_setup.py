"""Kafka topic provisioning script for Photoz."""

import os
import sys
from pathlib import Path
from typing import Any

import django
from confluent_kafka import KafkaException
from confluent_kafka.admin import AdminClient, NewTopic
from django.conf import settings

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bses.settings")
django.setup()

DEFAULT_TOPICS: dict[str, dict[str, Any]] = {
    "likes": {
        "name": "photo.events.likes",
        "partitions": 50,
        "replication_factor": 1,
        "dlq": True,
    },
    "uploads": {
        "name": "photo.events.uploads",
        "partitions": 50,
        "replication_factor": 1,
        "dlq": True,
    },
    "follows": {
        "name": "photo.events.follows",
        "partitions": 50,
        "replication_factor": 1,
        "dlq": True,
    },
}


def _collect_topics_to_create(
    topics_config: dict[str, dict[str, Any]], existing: set[str]
) -> list[NewTopic]:
    """Identify which configured topics and DLQs are not yet created on the broker."""
    to_create: list[NewTopic] = []
    for topic_info in topics_config.values():
        name = topic_info["name"]
        partitions = topic_info.get("partitions", 50)
        replication = topic_info.get("replication_factor", 1)

        if name in existing:
            print(f"Topic '{name}' already exists, skipping.")
        else:
            to_create.append(
                NewTopic(name, num_partitions=partitions, replication_factor=replication)
            )

        if topic_info.get("dlq", False):
            dlq_name = topic_info.get("dlq_name", f"{name}.dlq")
            if dlq_name in existing:
                print(f"Topic '{dlq_name}' already exists, skipping.")
            else:
                to_create.append(
                    NewTopic(dlq_name, num_partitions=partitions, replication_factor=replication)
                )
    return to_create


def create_topics() -> None:
    """Provision configured Kafka topics and dead-letter queues idempotently."""
    bootstrap_servers = getattr(
        settings, "KAFKA_BOOTSTRAP_SERVERS", os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    )
    admin_client = AdminClient({"bootstrap.servers": bootstrap_servers})

    cluster_metadata = admin_client.list_topics(timeout=10)
    existing_topics = set(cluster_metadata.topics.keys())

    topics_config = getattr(settings, "KAFKA_TOPICS", DEFAULT_TOPICS)
    topics_to_create = _collect_topics_to_create(topics_config, existing_topics)

    if not topics_to_create:
        print("All configured topics already exist. No new topics to create.")
        return

    print(f"Creating {len(topics_to_create)} new topic(s) on {bootstrap_servers}...")
    futures = admin_client.create_topics(topics_to_create)

    for topic, future in futures.items():
        try:
            future.result()
            print(f"Topic '{topic}' created successfully.")
        except KafkaException as err:
            print(f"Failed to create topic '{topic}': {err}")


if __name__ == "__main__":
    create_topics()
