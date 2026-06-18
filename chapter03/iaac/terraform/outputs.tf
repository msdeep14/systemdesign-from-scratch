output "load_balancer_public_ip" {
  value       = aws_instance.lb_node.public_ip
  description = "The public IP address of the Nginx Load Balancer. Access the app here via HTTP."
}

output "database_private_ip" {
  value       = try(aws_instance.db_node[0].private_ip, var.existing_db_private_ip)
  description = "The private IP address of the Database Node."
}

output "app_server_asg_name" {
  value       = aws_autoscaling_group.app_nodes.name
  description = "The name of the Auto Scaling Group managing the App Servers."
}
