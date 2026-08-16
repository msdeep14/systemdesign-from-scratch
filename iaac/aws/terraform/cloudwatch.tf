resource "aws_cloudwatch_log_group" "app_logs" {
  name              = "photoz-app-logs${local.env_suffix}"
  retention_in_days = 7

  tags = {
    Name = "photoz-app-logs${local.env_suffix}"
  }
}

resource "aws_cloudwatch_log_group" "lb_logs" {
  name              = "photoz-lb-logs${local.env_suffix}"
  retention_in_days = 7

  tags = {
    Name = "photoz-lb-logs${local.env_suffix}"
  }
}
