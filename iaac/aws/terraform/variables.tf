variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

# --- SSH Access ---
variable "app_key_name" {
  type        = string
  description = "Name of the AWS Key Pair for App nodes"
}

variable "db_key_name" {
  type        = string
  description = "Name of the AWS Key Pair for Database and Redis nodes"
}

variable "lb_key_name" {
  type        = string
  description = "Name of the AWS Key Pair for Load Balancer nodes"
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

variable "app_desired_capacity" {
  type        = number
  default     = 2
  description = "Desired number of App instances in the Auto Scaling Group"
}

variable "app_max_size" {
  type        = number
  default     = 4
  description = "Maximum number of App instances in the Auto Scaling Group"
}

variable "app_min_size" {
  type        = number
  default     = 2
  description = "Minimum number of App instances in the Auto Scaling Group"
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

variable "db_volume_size" {
  type        = number
  default     = 30
  description = "EBS root volume size in GB for the Primary Database and Replica nodes"
}


variable "s3_bucket_name" {
  type        = string
  description = "Existing S3 Bucket Name for media storage"
}



variable "db_replica_count" {
  description = "Number of database read replicas"
  type        = number
  default     = 1
}

variable "create_redis_node" {
  type        = bool
  default     = true
  description = "Set to true to provision Redis nodes"
}

variable "redis_instance_type" {
  type        = string
  default     = "t3.micro"
  description = "EC2 instance type for the Redis primary node"
}

variable "redis_replica_count" {
  type        = number
  default     = 3
  description = "Number of Redis read replica nodes"
}

variable "redis_replica_instance_type" {
  type        = string
  default     = "t3.micro"
  description = "EC2 instance type for Redis replica nodes"
}

variable "redis_master_name" {
  type        = string
  default     = "mymaster"
  description = "Redis Sentinel master monitor name"
}

variable "create_redis_feeds_node" {
  type        = bool
  default     = true
  description = "Set to true to provision dedicated Redis newsfeed timeline nodes"
}

variable "redis_feeds_instance_type" {
  type        = string
  default     = "t3.micro"
  description = "EC2 instance type for the Redis feeds primary node"
}

variable "redis_feeds_replica_count" {
  type        = number
  default     = 1
  description = "Number of Redis feeds read replica nodes"
}

variable "redis_feeds_replica_instance_type" {
  type        = string
  default     = "t3.micro"
  description = "EC2 instance type for Redis feeds replica nodes"
}

variable "redis_feeds_master_name" {
  type        = string
  default     = "feeds-master"
  description = "Redis Sentinel master monitor name for feeds cluster"
}

variable "create_redis_sentinel_node" {
  type        = bool
  default     = true
  description = "Set to true to provision a dedicated Redis Sentinel cluster"
}

variable "redis_sentinel_count" {
  type        = number
  default     = 3
  description = "Number of dedicated Redis Sentinel nodes for quorum"
}

variable "redis_sentinel_instance_type" {
  type        = string
  default     = "t3.nano"
  description = "EC2 instance type for dedicated Redis Sentinel nodes (AL2023 Minimal)"
}

variable "enable_auto_schedule" {
  type        = bool
  default     = false
  description = "Enable automated sleep/wake cron jobs via SSM parameter flag"
}

variable "create_kafka_cluster" {
  type        = bool
  default     = true
  description = "Set to true to provision a self-managed Kafka KRaft cluster (3 controllers + 3 brokers)"
}

variable "kafka_key_name" {
  type        = string
  default     = "photoz-kafka-key"
  description = "Name of the AWS Key Pair for Kafka Controller and Broker nodes"
}

variable "kafka_controller_instance_type" {
  type        = string
  default     = "t3.medium"
  description = "EC2 instance type for Kafka KRaft Controller nodes"
}

variable "kafka_broker_instance_type" {
  type        = string
  default     = "t3.medium"
  description = "EC2 instance type for Kafka Broker nodes"
}

variable "kafka_ebs_volume_size" {
  type        = number
  default     = 10
  description = "Size in GB of the dedicated gp3 EBS volume attached to each Kafka Broker"
}
