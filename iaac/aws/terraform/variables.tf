variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

# --- SSH Access ---
variable "key_name" {
  type        = string
  description = "Name of the existing AWS Key Pair to attach to the instances for SSH access"
}

# --- Module Toggles ---
variable "create_vpc" {
  type        = bool
  default     = true
  description = "Set to false to use an existing VPC"
}

variable "create_db_node" {
  type        = bool
  default     = true
  description = "Set to false to preserve the database node during teardowns"
}

variable "existing_db_private_ip" {
  type        = string
  default     = ""
  description = "If create_db_node is false, the private IP of the preserved database node"
}

variable "seed_database" {
  description = "If true, automatically seeds the database with test data (100k photos, etc.) on launch"
  type        = bool
  default     = false
}

variable "existing_vpc_id" {
  type    = string
  default = ""
}

variable "existing_public_subnet_ids" {
  type    = list(string)
  default = []
}

variable "create_security_groups" {
  type    = bool
  default = true
}

variable "existing_db_sg_id" {
  type    = string
  default = ""
}

variable "existing_app_sg_id" {
  type    = string
  default = ""
}

variable "existing_lb_sg_id" {
  type    = string
  default = ""
}

variable "create_iam_role" {
  type    = bool
  default = true
}

variable "existing_iam_instance_profile_name" {
  type    = string
  default = ""
}

# --- Application Secrets (Passed via .tfvars) ---
variable "db_password" {
  type        = string
  description = "PostgreSQL Database Password"
  sensitive   = true
}

variable "aws_access_key_id" {
  type        = string
  description = "AWS Access Key for S3"
  sensitive   = true
}

variable "aws_secret_access_key" {
  type        = string
  description = "AWS Secret Key for S3"
  sensitive   = true
}

variable "django_secret_key" {
  type        = string
  description = "Django SECRET_KEY. Must be identical across all App Nodes."
  sensitive   = true
}

variable "lb_instance_type" {
  type        = string
  default     = "t3.micro"
  description = "EC2 instance type for the Load Balancer node"
}

variable "app_instance_type" {
  type        = string
  default     = "t3.micro"
  description = "EC2 instance type for the App nodes"
}

variable "db_instance_type" {
  type        = string
  default     = "t3.micro"
  description = "EC2 instance type for the Primary Database node"
}

variable "db_replica_instance_type" {
  type        = string
  default     = "t3.micro"
  description = "EC2 instance type for the Database Replica nodes"
}

variable "s3_bucket_name" {
  type        = string
  description = "Existing S3 Bucket Name for media storage"
}

variable "github_token" {
  type        = string
  description = "Optional: GitHub Personal Access Token (PAT) for cloning the repository if it is private. Leave empty if the repository is public."
  sensitive   = true
  default     = ""
}

variable "db_replica_count" {
  description = "Number of database read replicas"
  type        = number
  default     = 1
}
