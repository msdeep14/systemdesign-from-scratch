output "load_balancer_public_ip" {
  value       = aws_instance.lb_node.public_ip
  description = "The public IP address of the Nginx Load Balancer. Access the app here via HTTP."
}

output "database_private_ip" {
  value       = try(aws_instance.db_node[0].private_ip, var.existing_db_private_ip)
  description = "The private IP address of the Primary Database Node."
}

output "database_replica_private_ips" {
  value       = aws_instance.db_replica[*].private_ip
  description = "The private IP addresses of the Database Replicas."
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
