output "load_balancer_public_ip" {
  value       = aws_instance.lb_node.public_ip
  description = "The public IP address of the Nginx Load Balancer. Access the app here via HTTP."
}

output "redis_public_ip" {
  value       = try(aws_instance.redis_node[0].public_ip, "N/A")
  description = "The public IP address of the Redis Node."
}

output "app_server_asg_name" {
  value       = aws_autoscaling_group.app_nodes.name
  description = "The name of the Auto Scaling Group managing the App Servers."
}

output "database_public_ip" {
  value       = try(aws_instance.db_node[0].public_ip, "N/A")
  description = "The public IP address of the Primary Database Node."
}

output "database_replica_public_ips" {
  value       = aws_instance.db_replica[*].public_ip
  description = "The public IP addresses of the Database Replicas."
}

data "aws_instances" "app_nodes" {
  filter {
    name   = "tag:aws:autoscaling:groupName"
    values = [aws_autoscaling_group.app_nodes.name]
  }
  
  # Ensure we query after the ASG is created
  depends_on = [aws_autoscaling_group.app_nodes]
}

output "app_server_public_ips" {
  value       = data.aws_instances.app_nodes.public_ips
  description = "The public IP addresses of the App Servers currently in the ASG (may take a minute to populate)."
}

output "test_user_credentials" {
  value       = var.seed_database ? "Username: test_user | Password: password123" : "Database not seeded"
  description = "Login credentials for the test user if seed_database is true"
}

output "cloudfront_domain" {
  value       = aws_cloudfront_distribution.photoz_cdn.domain_name
  description = "The CloudFront distribution domain name. Set this as AWS_S3_CUSTOM_DOMAIN in the app .env"
}

output "cloudfront_distribution_id" {
  value       = aws_cloudfront_distribution.photoz_cdn.id
  description = "The CloudFront distribution ID. Needed for cache invalidation on photo delete."
}

output "github_runner_public_ip" {
  value       = try(aws_instance.github_runner[0].public_ip, "N/A")
  description = "The public IP address of the GitHub Self-Hosted Runner."
}
