locals {
  kafka_monitored_topics = {
    likes = {
      name  = "photo.events.likes"
      group = "photoz-likes-group"
    }
    uploads = {
      name  = "photo.events.uploads"
      group = "photoz-uploads-group"
    }
    follows = {
      name  = "photo.events.follows"
      group = "photoz-followers-group"
    }
    notifications = {
      name  = "photo.events.notifications"
      group = "photoz-notifications-group"
    }
    deletions = {
      name  = "photo.events.deletions"
      group = "photoz-deletions-group"
    }
  }
}

# -----------------------------------------------------------------------------
# CloudWatch Metric Alarms for Kafka Consumer Lag (>5,000 messages)
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "kafka_high_lag" {
  for_each            = var.create_kafka_cluster ? local.kafka_monitored_topics : {}
  alarm_name          = "photoz-kafka-high-lag-${each.key}${local.env_suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ConsumerLag"
  namespace           = "PhotoZ/Kafka"
  period              = 60
  statistic           = "Maximum"
  threshold           = 5000
  alarm_description   = "Alarm triggered when Kafka consumer lag for ${each.value.name} exceeds 5000 messages for 2 consecutive minutes."

  dimensions = {
    Topic         = each.value.name
    ConsumerGroup = each.value.group
  }
}

# -----------------------------------------------------------------------------
# CloudWatch Metric Alarms for Kafka Message Time Lag (>300 seconds)
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "kafka_high_timelag" {
  for_each            = var.create_kafka_cluster ? local.kafka_monitored_topics : {}
  alarm_name          = "photoz-kafka-high-timelag-${each.key}${local.env_suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "TimeLagSeconds"
  namespace           = "PhotoZ/Kafka"
  period              = 60
  statistic           = "Maximum"
  threshold           = 300
  alarm_description   = "Alarm triggered when processing delay for ${each.value.name} exceeds 300 seconds (5 minutes)."

  dimensions = {
    Topic         = each.value.name
    ConsumerGroup = each.value.group
  }
}

# -----------------------------------------------------------------------------
# CloudWatch Metric Alarms for Dead Letter Queue Accumulation (>0 records)
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "kafka_dlq_records" {
  for_each            = var.create_kafka_cluster ? local.kafka_monitored_topics : {}
  alarm_name          = "photoz-kafka-dlq-alert-${each.key}${local.env_suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "DLQDepth"
  namespace           = "PhotoZ/Kafka"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Alarm triggered immediately when poison pill or failed messages enter ${each.value.name}.dlq."

  dimensions = {
    Topic = "${each.value.name}.dlq"
  }
}

