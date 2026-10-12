# Implementation Plan - v0

## Phase: Gunicorn Slow Photo Uploads & Nginx

### The Problem
Gunicorn uses synchronous workers by default. If a user on a slow network uploads a large file, the worker is blocked reading the incoming request body. Multiple slow clients can exhaust all available workers, rendering the application unresponsive.

### The Solution (Pending)
Nginx buffers request bodies asynchronously. It can receive the slow upload while Gunicorn remains free. Once fully received, Nginx passes the request to Gunicorn over the fast local network.

### Current Implementation Steps
1. Replicate the problem using `simulate_slow_upload.py` (which intentionally sends data in tiny chunks with long sleeps).
2. Measure responsiveness with `test_responsiveness.py`.
3. (Future) Implement Nginx to resolve the issue.

## Phase: Terraform IaC Automation

### The Problem
Manually provisioning the 3-tier decoupled architecture (VPC, Security Groups, IAM Roles, EC2 instances, and configuration) is tedious and error-prone.

### The Solution
Use Terraform to automate the deployment. The implementation will include conditional logic for VPCs, Security Groups, and IAM roles to allow reusing existing infrastructure. It will automatically inject the EC2 self-IP into `.env` and `awslogs-stream`, and dynamically configure `nginx.conf` via `user_data` scripts. A custom `destroy.sh` wrapper will allow targeted cleanup.

## Terraform IaC - Database Persistence & Automated Backups
*   **Analysis:** The user requested the ability to skip destroying the database instance during infrastructure teardown, re-use the preserved database instance in future launches, and back up the database data.
*   **Decisions:** 
    *   Introduce `--skip-db` to `destroy.sh` which executes `terraform state rm 'aws_instance.db_node[0]'` to leave the DB running and untracked.
    *   Introduce `create_db_node` and `existing_db_private_ip` variables to `variables.tf`.
    *   Conditionally provision the DB node in `main.tf` and dynamically feed `existing_db_private_ip` to the App nodes if `create_db_node` is `false`.
    *   Inject a daily `cron` script into the DB node's `user_data` that runs `pg_dump` and uploads the snapshot to the existing S3 bucket using the IAM profile.
    *   Attach `AmazonS3FullAccess` to the EC2 IAM Role to allow the DB node to execute `aws s3 cp`.

## Phase: Consul Service Discovery
### The Problem
Hardcoded IPs in the Load Balancer Nginx configuration prevent the architecture from scaling dynamically. If an Auto Scaling Group adds or replaces an App Node, a human must manually SSH in and update the `nginx.conf` file.

### The Solution
Use HashiCorp Consul to automate Service Discovery.
*   Run a central Consul Server on the LB node.
*   Run Consul Agents on the App Nodes to constantly perform HTTP health checks against the Django container.
*   Run Consul Template on the LB node to automatically rewrite the `nginx.conf` upstream block and execute `nginx -s reload` in milliseconds whenever a node joins or dies.

## Phase: Kafka Dead Letter Queue (DLQ) & Retry Policy (Phase 5)
### The Problem
Poison pill records (e.g., malformed JSON bytes or foreign key integrity constraint violations) or transient database connection blips can cause consumers to either crash, get stuck in an infinite retry loop, or silently discard unprocessable messages without diagnostic traceability.

### The Solution
Implement an exponential backoff retry policy for transient operational errors and route poison pills / deserialization failures to dedicated Dead Letter Queue topics (`{topic}.dlq`).
*   Add `publish_to_dlq` in `bses.kafka` wrapping failed payloads in a diagnostic envelope.
*   Add exponential backoff retries in `BaseKafkaConsumerCommand` for transient errors.
*   Route deserialization failures, schema errors, and poison pills to DLQ and commit offset so consumer partitions never deadlock.

## Phase: Celery Decommissioning & Asynchronous Workflow Migration (Phase 6)
### The Problem
Celery workers and Celery Beat introduce unnecessary operational overhead, Redis queue bottlenecks, and dual message broker complexity alongside Kafka.
### The Solution
Migrate all remaining asynchronous workflows to Kafka:
*   Route notifications (`photo.events.notifications`) and photo deletions (`photo.events.deletions`) through Kafka consumers.
*   Update `bulk_record_likes` to atomically increment `Photo.likes_count` in PostgreSQL on batch consumption, eliminating periodic Celery Beat flushes for both likes and follower counts.
*   Decommission Celery task files and configuration across the Django project.
*   Remove Celery services from `docker-compose.yml` and `docker-compose-app.yml`, purge Celery dependencies from `requirements.txt`, and clean up obsolete Celery Beat security group ingress rules in `iaac/aws/terraform/security.tf`.

## Phase: AWS Infrastructure Deployment (Terraform & KRaft EC2) (Phase 7)
### The Problem
Deploying Kafka for production workloads requires resilient consensus, isolation between control operations and high-throughput data operations, fault tolerance across data centers, and persistent high-speed disk storage.
### The Solution
Provision a self-managed KRaft Kafka cluster on AWS EC2 using Terraform:
*   Multi-AZ VPC subnets across 3 Availability Zones.
*   Control Plane: 3 dedicated KRaft Controllers forming a consensus quorum.
*   Data Plane: 3 dedicated Brokers handling topic partition storage and throughput with dedicated gp3 EBS volumes.
*   Strict security groups isolating controller quorum (9093) and broker client/replication traffic (9092).
*   Automatic injection of `KAFKA_BOOTSTRAP_SERVERS` into App node environments.


