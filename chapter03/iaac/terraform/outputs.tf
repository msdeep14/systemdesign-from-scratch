output "load_balancer_public_ip" {
  value       = aws_instance.lb_node.public_ip
  description = "The public IP address of the Nginx Load Balancer. Access the app here via HTTP."
}

output "database_private_ip" {
  value       = aws_instance.db_node.private_ip
  description = "The private IP address of the Database Node."
}

output "app_server_private_ips" {
  value       = aws_instance.app_node[*].private_ip
  description = "The private IP addresses of the App Servers."
}
