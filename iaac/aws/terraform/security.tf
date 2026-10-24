data "http" "my_ip" {
  url = "https://ipv4.icanhazip.com"
}

locals {
  my_ip_cidr = "${chomp(data.http.my_ip.response_body)}/32"
}

resource "aws_security_group" "lb" {
  count       = var.create_security_groups ? 1 : 0
  name        = "photoz-lb-sg${local.env_suffix}"
  description = "Allow HTTP inbound traffic"
  vpc_id      = local.vpc_id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.my_ip_cidr]
  }

  ingress {
    description = "Consul internal TCP"
    from_port   = 8300
    to_port     = 8302
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    description = "Consul internal UDP"
    from_port   = 8301
    to_port     = 8302
    protocol    = "udp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "app" {
  count       = var.create_security_groups ? 1 : 0
  name        = "photoz-app-sg${local.env_suffix}"
  description = "Allow traffic from LB"
  vpc_id      = local.vpc_id

  ingress {
    description     = "HTTP from LB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.lb[0].id]
  }

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.my_ip_cidr]
  }


  ingress {
    description = "Consul internal TCP"
    from_port   = 8300
    to_port     = 8302
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    description = "Consul internal UDP"
    from_port   = 8301
    to_port     = 8302
    protocol    = "udp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "db" {
  count       = var.create_security_groups ? 1 : 0
  name        = "photoz-db-sg${local.env_suffix}"
  description = "Allow Postgres traffic from App"
  vpc_id      = local.vpc_id

  ingress {
    description     = "Postgres from App"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app[0].id]
  }

  ingress {
    description     = "PgBouncer from App"
    from_port       = 6432
    to_port         = 6432
    protocol        = "tcp"
    security_groups = [aws_security_group.app[0].id]
  }

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.my_ip_cidr]
  }

  ingress {
    description     = "Postgres from Replica (Streaming WAL)"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.db_replica[0].id]
  }


  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "db_replica" {
  count       = var.create_security_groups ? 1 : 0
  name        = "photoz-db-replica-sg${local.env_suffix}"
  description = "Allow Postgres traffic for Replica"
  vpc_id      = local.vpc_id

  ingress {
    description     = "PgBouncer from App"
    from_port       = 6432
    to_port         = 6432
    protocol        = "tcp"
    security_groups = [aws_security_group.app[0].id]
  }

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.my_ip_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

locals {
  lb_sg_id  = var.create_security_groups ? aws_security_group.lb[0].id : var.existing_lb_sg_id
  app_sg_id = var.create_security_groups ? aws_security_group.app[0].id : var.existing_app_sg_id
  db_sg_id  = var.create_security_groups ? aws_security_group.db[0].id : var.existing_db_sg_id
}

resource "aws_security_group" "redis" {
  count       = var.create_security_groups && var.create_redis_node ? 1 : 0
  name        = "photoz-redis-sg${local.env_suffix}"
  description = "Allow Redis traffic from App"
  vpc_id      = local.vpc_id

  ingress {
    description     = "Redis from App"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app[0].id]
  }

  ingress {
    description = "Redis Replication within VPC"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    description     = "Redis Sentinel from App"
    from_port       = 26379
    to_port         = 26379
    protocol        = "tcp"
    security_groups = [aws_security_group.app[0].id]
  }

  ingress {
    description = "Redis Sentinel Gossip within VPC"
    from_port   = 26379
    to_port     = 26379
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.my_ip_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

locals {
  redis_sg_id = var.create_security_groups && var.create_redis_node ? aws_security_group.redis[0].id : ""
}

resource "aws_security_group" "kafka_controller" {
  count       = var.create_security_groups && var.create_kafka_cluster ? 1 : 0
  name        = "photoz-kafka-controller-sg${local.env_suffix}"
  description = "Allow KRaft Controller Quorum traffic"
  vpc_id      = local.vpc_id

  ingress {
    description = "KRaft Controller Quorum"
    from_port   = 9093
    to_port     = 9093
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.my_ip_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "kafka_broker" {
  count       = var.create_security_groups && var.create_kafka_cluster ? 1 : 0
  name        = "photoz-kafka-broker-sg${local.env_suffix}"
  description = "Allow Kafka Broker traffic from VPC"
  vpc_id      = local.vpc_id

  ingress {
    description = "Kafka Broker PLAINTEXT from VPC"
    from_port   = 9092
    to_port     = 9092
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.my_ip_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

locals {
  kafka_controller_sg_id = var.create_security_groups && var.create_kafka_cluster ? aws_security_group.kafka_controller[0].id : ""
  kafka_broker_sg_id     = var.create_security_groups && var.create_kafka_cluster ? aws_security_group.kafka_broker[0].id : ""
}
