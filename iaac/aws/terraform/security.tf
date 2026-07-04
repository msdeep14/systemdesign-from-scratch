data "http" "my_ip" {
  url = "https://ipv4.icanhazip.com"
}

locals {
  my_ip_cidr = "${chomp(data.http.my_ip.response_body)}/32"
}

resource "aws_security_group" "lb" {
  count       = var.create_security_groups ? 1 : 0
  name        = "photoz-lb-sg"
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
  name        = "photoz-app-sg"
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
  name        = "photoz-db-sg"
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
