locals {
  repo_url = "https://github.com/msdeep14/systemdesign-from-scratch.git"
  env_suffix = terraform.workspace == "default" ? "" : "-${terraform.workspace}"
  s3_bucket_name = "${var.s3_bucket_name}${local.env_suffix}"
  runner_label = terraform.workspace == "default" ? "prod" : terraform.workspace
}

data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-*-26.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical -- This ensures ubuntu image being downloaded from official ubuntu upstream
}

resource "aws_instance" "db_node" {
  count                  = var.create_db_node ? 1 : 0
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.db_instance_type
  subnet_id              = local.subnet_ids[0]
  key_name               = var.db_key_name
  vpc_security_group_ids = [local.db_sg_id]
  iam_instance_profile   = local.iam_instance_profile

  lifecycle {
    ignore_changes = [key_name]
  }

  user_data = <<-EOF
#!/bin/bash
sudo apt-get update && sudo apt-get install -y git
aws s3 cp s3://photoz-secrets-${var.aws_region}${local.env_suffix}/secrets.env /tmp/secrets.env || true
if [ -f /tmp/secrets.env ]; then
  source /tmp/secrets.env
fi

if [ -n "$GITHUB_TOKEN" ] && [ "$GITHUB_TOKEN" != "None" ]; then
  git clone https://$${GITHUB_TOKEN}@github.com/msdeep14/systemdesign-from-scratch.git /home/ubuntu/systemdesign-from-scratch
else
  git clone ${local.repo_url} /home/ubuntu/systemdesign-from-scratch
fi
chown -R ubuntu:ubuntu /home/ubuntu/systemdesign-from-scratch
cd /home/ubuntu/systemdesign-from-scratch/photoz

chmod +x configure_dependencies.sh
sudo ./configure_dependencies.sh

LOCAL_IP=$(hostname -I | awk '{print $1}')
cat <<-ENV > .env
POSTGRES_DB=bses
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
USE_S3=True
AWS_STORAGE_BUCKET_NAME=${local.s3_bucket_name}
AWS_S3_REGION_NAME=${var.aws_region}
SECRET_KEY=$SECRET_KEY
POSTGRES_HOST=127.0.0.1
NODE_IP=$LOCAL_IP
ENV

docker compose -f docker-compose-db.yml up -d

# Wait for DB to be fully ready before setting up replication
sudo apt-get install -y postgresql-client
until pg_isready -h 127.0.0.1 -U postgres; do
  echo "Waiting for postgres to start..."
  sleep 2
done

# Automate Replication Setup for Clean Deployments
docker exec -i photoz-db-1 bash < ./postgres-init/02-setup-replication.sh
docker compose -f docker-compose-db.yml restart db

# Wait for the DB to come back up after restart
until pg_isready -h 127.0.0.1 -U postgres; do
  echo "Waiting for postgres to restart..."
  sleep 2
done

# Create one physical replication slot per replica.
# See postgres-init/03-create-replication-slots.sh for manual usage.
REPLICA_COUNT=${var.db_replica_count} bash ./postgres-init/03-create-replication-slots.sh

# Setup automated S3 backups
cat <<'CRON' > /etc/cron.daily/db_backup
#!/bin/bash
docker exec photoz-db pg_dump -U postgres bses > /tmp/bses_backup.sql
aws s3 cp /tmp/bses_backup.sql s3://${local.s3_bucket_name}/db_backups/bses_backup_\$(date +%F).sql
CRON
chmod +x /etc/cron.daily/db_backup

if [ "${var.seed_database}" = "true" ]; then
  echo "Seeding database..."
  sudo apt-get install -y python3-venv libpq-dev postgresql-client
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  
  # Wait for DB to be fully ready to accept connections
  until pg_isready -h 127.0.0.1 -U postgres; do
    echo "Waiting for postgres to start..."
    sleep 2
  done
  
  # Ensure schema exists before seeding
  python manage.py migrate
  
  python ../chapter04/query_optimization/seed_data.py --reset
fi
EOF

  tags = { Name = "photoz-db-node${local.env_suffix}" }
}

resource "aws_instance" "db_replica" {
  count                  = var.db_replica_count
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.db_replica_instance_type
  subnet_id              = local.subnet_ids[count.index % length(local.subnet_ids)]
  key_name               = var.db_key_name
  vpc_security_group_ids = [aws_security_group.db_replica[0].id]
  iam_instance_profile   = local.iam_instance_profile

  lifecycle {
    ignore_changes = [key_name]
  }

  user_data = <<-EOF
#!/bin/bash
sudo apt-get update && sudo apt-get install -y git
aws s3 cp s3://photoz-secrets-${var.aws_region}${local.env_suffix}/secrets.env /tmp/secrets.env || true
if [ -f /tmp/secrets.env ]; then
  source /tmp/secrets.env
fi

if [ -n "$GITHUB_TOKEN" ] && [ "$GITHUB_TOKEN" != "None" ]; then
  git clone https://$${GITHUB_TOKEN}@github.com/msdeep14/systemdesign-from-scratch.git /home/ubuntu/systemdesign-from-scratch
else
  git clone ${local.repo_url} /home/ubuntu/systemdesign-from-scratch
fi
chown -R ubuntu:ubuntu /home/ubuntu/systemdesign-from-scratch
cd /home/ubuntu/systemdesign-from-scratch/photoz

chmod +x configure_dependencies.sh
sudo ./configure_dependencies.sh

LOCAL_IP=$(hostname -I | awk '{print $1}')
cat <<-ENV > .env
POSTGRES_DB=bses
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
USE_S3=True
AWS_STORAGE_BUCKET_NAME=${local.s3_bucket_name}
AWS_S3_REGION_NAME=${var.aws_region}
AWS_REGION=${var.aws_region}
DEBUG_MODE=False
SECRET_KEY=$SECRET_KEY
PRIMARY_DB_HOST=${var.create_db_node ? aws_instance.db_node[0].private_ip : var.existing_db_private_ip}
REPLICA_SLOT_NAME=replica_${count.index + 1}
NODE_IP=$LOCAL_IP
ENV

docker compose -f docker-compose-replica.yml up -d
EOF

  tags = { Name = "photoz-db-replica-${count.index + 1}${local.env_suffix}" }
}

resource "aws_instance" "redis_node" {
  count                  = var.create_redis_node ? 1 : 0
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.redis_instance_type
  subnet_id              = local.subnet_ids[0]
  key_name               = var.db_key_name
  vpc_security_group_ids = [local.redis_sg_id]
  iam_instance_profile   = local.iam_instance_profile

  lifecycle {
    ignore_changes = [key_name]
  }

  user_data = <<-EOF
#!/bin/bash
sudo apt-get update
sudo apt-get install -y redis-server
sudo sed -i 's/^bind 127.0.0.1 -::1/bind 0.0.0.0/' /etc/redis/redis.conf
sudo sed -i 's/^protected-mode yes/protected-mode no/' /etc/redis/redis.conf
sudo systemctl restart redis-server
sudo systemctl enable redis-server
EOF

  tags = { Name = "photoz-redis-node${local.env_suffix}" }
}

resource "aws_launch_template" "app_node" {
  name_prefix   = "photoz-app-node${local.env_suffix}-"
  image_id      = data.aws_ami.ubuntu.id
  instance_type = var.app_instance_type
  key_name      = var.app_key_name

  network_interfaces {
    security_groups             = [local.app_sg_id]
    associate_public_ip_address = true
  }

  iam_instance_profile {
    name = local.iam_instance_profile
  }

  user_data = base64encode(<<EOF
#!/bin/bash
sudo apt-get update && sudo apt-get install -y git
aws s3 cp s3://photoz-secrets-${var.aws_region}${local.env_suffix}/secrets.env /tmp/secrets.env || true
if [ -f /tmp/secrets.env ]; then
  source /tmp/secrets.env
fi

if [ -n "$GITHUB_TOKEN" ] && [ "$GITHUB_TOKEN" != "None" ]; then
  git clone https://$${GITHUB_TOKEN}@github.com/msdeep14/systemdesign-from-scratch.git /home/ubuntu/systemdesign-from-scratch
else
  git clone ${local.repo_url} /home/ubuntu/systemdesign-from-scratch
fi
chown -R ubuntu:ubuntu /home/ubuntu/systemdesign-from-scratch
cd /home/ubuntu/systemdesign-from-scratch/photoz

chmod +x configure_dependencies.sh
sudo ./configure_dependencies.sh

LOCAL_IP=$(hostname -I | awk '{print $1}')
cat <<-ENV > .env
POSTGRES_DB=bses
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
USE_S3=True
AWS_STORAGE_BUCKET_NAME=${local.s3_bucket_name}
AWS_S3_REGION_NAME=${var.aws_region}
AWS_REGION=${var.aws_region}
DEBUG_MODE=False
SECRET_KEY=$SECRET_KEY
POSTGRES_HOST=${var.create_db_node ? aws_instance.db_node[0].private_ip : var.existing_db_private_ip}
REPLICA_DB_HOSTS=${var.db_replica_count > 0 ? join(",", aws_instance.db_replica[*].private_ip) : ""}
REPLICA_DB_PORT=6432
CONSUL_SERVER_IP=${aws_instance.lb_node.private_ip}
NODE_IP=$LOCAL_IP
REDIS_URL=${var.create_redis_node ? "redis://${aws_instance.redis_node[0].private_ip}:6379/1" : ""}
AWS_S3_CUSTOM_DOMAIN=${aws_cloudfront_distribution.photoz_cdn.domain_name}
CLOUDFRONT_DISTRIBUTION_ID=${aws_cloudfront_distribution.photoz_cdn.id}
ENV

docker compose -f docker-compose-app.yml up -d
EOF
  )

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "photoz-app-node${local.env_suffix}"
    }
  }
}

resource "aws_autoscaling_group" "app_nodes" {
  name                = "photoz-app-asg${local.env_suffix}"
  vpc_zone_identifier = local.subnet_ids
  desired_capacity    = 2
  max_size            = 4
  min_size            = 2

  depends_on = [aws_cloudwatch_log_group.app_logs]

  launch_template {
    id      = aws_launch_template.app_node.id
    version = "$Latest"
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
    }
  }

  tag {
    key                 = "Name"
    value               = "photoz-app-node${local.env_suffix}"
    propagate_at_launch = true
  }
}

resource "aws_autoscaling_policy" "scale_up" {
  name                   = "photoz-scale-up${local.env_suffix}"
  scaling_adjustment     = 1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 300
  autoscaling_group_name = aws_autoscaling_group.app_nodes.name
}

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  alarm_name          = "photoz-cpu-high${local.env_suffix}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Average"
  threshold           = 70

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.app_nodes.name
  }

  alarm_description = "This metric monitors ec2 cpu utilization"
  alarm_actions     = [aws_autoscaling_policy.scale_up.arn]
}

resource "aws_autoscaling_policy" "scale_down" {
  name                   = "photoz-scale-down${local.env_suffix}"
  scaling_adjustment     = -1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 300
  autoscaling_group_name = aws_autoscaling_group.app_nodes.name
}

resource "aws_cloudwatch_metric_alarm" "cpu_low" {
  alarm_name          = "photoz-cpu-low${local.env_suffix}"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Average"
  threshold           = 30

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.app_nodes.name
  }

  alarm_description = "This metric monitors ec2 cpu utilization"
  alarm_actions     = [aws_autoscaling_policy.scale_down.arn]
}

resource "aws_instance" "lb_node" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.lb_instance_type
  subnet_id              = local.subnet_ids[0]
  key_name               = var.lb_key_name
  vpc_security_group_ids = [local.lb_sg_id]
  iam_instance_profile   = local.iam_instance_profile

  lifecycle {
    ignore_changes = [key_name]
  }

  depends_on = [aws_cloudwatch_log_group.lb_logs]

  user_data = <<-EOF
#!/bin/bash
sudo apt-get update && sudo apt-get install -y git
aws s3 cp s3://photoz-secrets-${var.aws_region}${local.env_suffix}/secrets.env /tmp/secrets.env || true
if [ -f /tmp/secrets.env ]; then
  source /tmp/secrets.env
fi

if [ -n "$GITHUB_TOKEN" ] && [ "$GITHUB_TOKEN" != "None" ]; then
  git clone https://$${GITHUB_TOKEN}@github.com/msdeep14/systemdesign-from-scratch.git /home/ubuntu/systemdesign-from-scratch
else
  git clone ${local.repo_url} /home/ubuntu/systemdesign-from-scratch
fi
chown -R ubuntu:ubuntu /home/ubuntu/systemdesign-from-scratch
cd /home/ubuntu/systemdesign-from-scratch/photoz

chmod +x configure_dependencies.sh
sudo ./configure_dependencies.sh

LOCAL_IP=$(hostname -I | awk '{print $1}')
cat <<ENV > .env
AWS_REGION=${var.aws_region}
NODE_IP=$LOCAL_IP
ENV

docker compose -f docker-compose-lb.yml up -d
EOF

  tags = { Name = "photoz-lb-node${local.env_suffix}" }
}


resource "aws_ssm_parameter" "auto_schedule_enabled" {
  name  = "/photoz/${terraform.workspace}/auto_schedule_enabled"
  type  = "String"
  value = var.enable_auto_schedule ? "true" : "false"
}
