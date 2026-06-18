locals {
  repo_url = var.github_token != "" ? "https://${var.github_token}@github.com/msdeep14/systemdesign-from-scratch.git" : "https://github.com/msdeep14/systemdesign-from-scratch.git"
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
  key_name               = var.key_name
  vpc_security_group_ids = [local.db_sg_id]
  iam_instance_profile   = local.iam_instance_profile

  user_data = <<-EOF
    #!/bin/bash
    sudo apt-get update && sudo apt-get install -y git
    git clone ${local.repo_url} /home/ubuntu/systemdesign-from-scratch
    chown -R ubuntu:ubuntu /home/ubuntu/systemdesign-from-scratch
    cd /home/ubuntu/systemdesign-from-scratch/photoz
    
    chmod +x configure_dependencies.sh
    sudo ./configure_dependencies.sh

    LOCAL_IP=$(hostname -I | awk '{print $1}')
    cat <<ENV > .env
    POSTGRES_DB=bses
    POSTGRES_USER=postgres
    POSTGRES_PASSWORD=${var.db_password}
    USE_S3=True
    AWS_STORAGE_BUCKET_NAME=${var.s3_bucket_name}
    AWS_S3_REGION_NAME=${var.aws_region}
    AWS_REGION=${var.aws_region}
    DEBUG_MODE=False
    AWS_ACCESS_KEY_ID=${var.aws_access_key_id}
    AWS_SECRET_ACCESS_KEY=${var.aws_secret_access_key}
    SECRET_KEY=${var.django_secret_key}
    POSTGRES_HOST=127.0.0.1
    NODE_IP=$LOCAL_IP
    ENV

    docker compose -f docker-compose-db.yml up -d

    # Setup automated S3 backups
    cat <<'CRON' > /etc/cron.daily/db_backup
    #!/bin/bash
    docker exec photoz-db pg_dump -U postgres bses > /tmp/bses_backup.sql
    aws s3 cp /tmp/bses_backup.sql s3://${var.s3_bucket_name}/db_backups/bses_backup_\$(date +%F).sql
    CRON
    chmod +x /etc/cron.daily/db_backup
  EOF

  tags = { Name = "photoz-db-node" }
}

resource "aws_launch_template" "app_node" {
  name_prefix   = "photoz-app-node-"
  image_id      = data.aws_ami.ubuntu.id
  instance_type = var.app_instance_type
  key_name      = var.key_name

  network_interfaces {
    security_groups             = [local.app_sg_id]
    associate_public_ip_address = true
  }

  iam_instance_profile {
    name = local.iam_instance_profile
  }

  user_data = base64encode(<<-EOF
    #!/bin/bash
    sudo apt-get update && sudo apt-get install -y git
    git clone https://${var.github_token}@github.com/msdeep14/systemdesign-from-scratch.git /home/ubuntu/systemdesign-from-scratch
    chown -R ubuntu:ubuntu /home/ubuntu/systemdesign-from-scratch
    cd /home/ubuntu/systemdesign-from-scratch/photoz
    
    chmod +x configure_dependencies.sh
    sudo ./configure_dependencies.sh

    LOCAL_IP=$(hostname -I | awk '{print $1}')
    cat <<ENV > .env
    POSTGRES_DB=bses
    POSTGRES_USER=postgres
    POSTGRES_PASSWORD=${var.db_password}
    USE_S3=True
    AWS_STORAGE_BUCKET_NAME=${var.s3_bucket_name}
    AWS_S3_REGION_NAME=${var.aws_region}
    AWS_REGION=${var.aws_region}
    DEBUG_MODE=False
    AWS_ACCESS_KEY_ID=${var.aws_access_key_id}
    AWS_SECRET_ACCESS_KEY=${var.aws_secret_access_key}
    SECRET_KEY=${var.django_secret_key}
    POSTGRES_HOST=${var.create_db_node ? aws_instance.db_node[0].private_ip : var.existing_db_private_ip}
    NODE_IP=$LOCAL_IP
    CONSUL_SERVER_IP=${aws_instance.lb_node.private_ip}
    ENV

    docker compose -f docker-compose-app.yml up -d
  EOF
  )

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "photoz-app-node"
    }
  }
}

resource "aws_autoscaling_group" "app_nodes" {
  name                = "photoz-app-asg"
  vpc_zone_identifier = local.subnet_ids
  desired_capacity    = 2
  max_size            = 4
  min_size            = 2

  launch_template {
    id      = aws_launch_template.app_node.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "photoz-app-node"
    propagate_at_launch = true
  }
}

resource "aws_autoscaling_policy" "scale_up" {
  name                   = "photoz-scale-up"
  scaling_adjustment     = 1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 300
  autoscaling_group_name = aws_autoscaling_group.app_nodes.name
}

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  alarm_name          = "photoz-cpu-high"
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
  name                   = "photoz-scale-down"
  scaling_adjustment     = -1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 300
  autoscaling_group_name = aws_autoscaling_group.app_nodes.name
}

resource "aws_cloudwatch_metric_alarm" "cpu_low" {
  alarm_name          = "photoz-cpu-low"
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
  key_name               = var.key_name
  vpc_security_group_ids = [local.lb_sg_id]
  iam_instance_profile   = local.iam_instance_profile

  user_data = <<-EOF
    #!/bin/bash
    sudo apt-get update && sudo apt-get install -y git
    git clone ${local.repo_url} /home/ubuntu/systemdesign-from-scratch
    chown -R ubuntu:ubuntu /home/ubuntu/systemdesign-from-scratch
    cd /home/ubuntu/systemdesign-from-scratch/photoz
    
    chmod +x configure_dependencies.sh
    sudo ./configure_dependencies.sh

    cat <<ENV > .env
    AWS_REGION=${var.aws_region}
    NODE_IP=\$(hostname -I | awk '{print \$1}')
    ENV

    docker compose -f docker-compose-lb.yml up -d
  EOF

  tags = { Name = "photoz-lb-node" }
}
