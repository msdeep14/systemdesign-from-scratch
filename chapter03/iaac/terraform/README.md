# Photoz Infrastructure as Code (Terraform)

This directory contains the automated Terraform setup to provision the 3-tier decoupled architecture for the Photoz application, as described in `chapter03/decoupled_architecture/aws-deployment-guide.md`. 

Instead of manually creating instances, configuring `.env` variables, and starting Docker Compose on each server, this Terraform module orchestrates everything seamlessly.

## Architecture & Security Setup

The Terraform setup provisions exactly what is documented in the deployment guide. Here is a breakdown of all the files in this directory and what they accomplish:

| File | Description & Accomplishments |
| :--- | :--- |
| **`variables.tf`** | Declares all dynamic inputs (passwords, SSH keys, AWS credentials) and feature flags (`create_vpc`, `create_iam_role`). Allows you to cleanly override configurations via `.tfvars` without touching source code. |
| **`provider.tf`** | Configures the Terraform `aws` and `http` providers, specifying the region to deploy resources into. |
| **`network.tf`** | Provisions a dedicated VPC (`10.0.0.0/16`), an Internet Gateway, Route Tables, and Public Subnets to host your EC2 instances. Can conditionally skip creation to map to your existing VPC. |
| **`security.tf`** | Creates strict, decoupled Security Groups. Automatically fetches your local machine's IP to lock down port 22 (SSH). Routes Port 80 to the Load Balancer, Port 8000 strictly from LB to App nodes, and Port 5432 strictly from App to DB node. |
| **`iam.tf`** | Creates an AWS IAM Role with `CloudWatchLogsFullAccess` and an Instance Profile, automatically attaching it to all EC2 instances to enable native distributed logging. |
| **`main.tf`** | The core orchestration file. Provisions 1 DB Node, 2 App Nodes, and 1 LB Node using Ubuntu 26.04. Automatically injects `user_data` shell scripts on boot to install Docker, generate `.env` files with the dynamic private IPs, configure Nginx, and launch the clusters. |
| **`outputs.tf`** | Exposes the public IP address of the newly provisioned Load Balancer directly to your console after `terraform apply` finishes. |
| **`destroy.sh`** | A custom bash wrapper around `terraform destroy` that accepts flags (e.g., `--skip-vpc`) to safely untrack base infrastructure from the state file, allowing for targeted teardowns to save costs without destroying persistent foundations. |
| **`terraform.tfvars`** | A local (git-ignored) configuration file where you define your secure passwords, existing SSH key names, and S3 credentials. |

### Automated Bootstrapping (`user_data`)
The magic happens via EC2 `user_data` scripts. Terraform automatically:
1. Installs Docker using `configure_dependencies.sh`.
2. Generates the `.env` files. It dynamically reads the DB node's Private IP and passes it to the App nodes.
3. Automatically writes the Nginx configuration file (`nginx.conf`) with the dynamically assigned Private IPs of the App nodes.
4. Starts the respective `docker-compose-*.yml` files.

## Prerequisites

### 1. AWS IAM Permissions
The AWS IAM User whose Access Key and Secret Key you provide in the `.tfvars` file **must** have permissions to create the required infrastructure. 

For security, avoid using an Administrator account. Instead, log into the AWS IAM Console, select your user, and attach the following specific managed policies:
*   **`AmazonEC2FullAccess`** (To provision Instances, Security Groups, and fetch AMIs)
*   **`AmazonVPCFullAccess`** (To provision the VPC, Subnets, and Route Tables)
*   **`IAMFullAccess`** (To create the CloudWatch logging roles and Instance Profiles)
*   **`AmazonS3FullAccess`** (For S3 access and management)
*   **`CloudWatchLogsFullAccess`** (To create and manage log groups)

### 2. Install Terraform
Before you can spin up the infrastructure, you must have Terraform installed on your machine. Terraform is a standalone binary (not a Python package), so you cannot install it via `pip`.

**To install Terraform on Mac (using Homebrew):**
```bash
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
```

You can verify the installation by running:
```bash
terraform -v
```

## How to Spin Up Resources

1. Initialize Terraform to download the AWS and HTTP providers:
   ```bash
   terraform init
   ```
2. Create a `terraform.tfvars` file to store your secrets (this file is ignored by Git):
   ```hcl
   key_name              = "your-existing-aws-ssh-key-name"
   db_password           = "your_secure_postgres_password"
   s3_bucket_name        = "your-existing-s3-bucket-name"
   aws_access_key_id     = "AKI..."
   aws_secret_access_key = "..."
   github_token          = "ghp_..." # OPTIONAL
   django_secret_key     = "your-django-secret-key"

   # --- Optional Instance Type Overrides ---
   # Uncomment and change these if you want to scale up from the default t3.micro
   # lb_instance_type  = "t3.small"
   # app_instance_type = "t3.medium"
   # db_instance_type  = "t3.medium"

   # --- Optional Existing Database Override ---
   # If you used ./destroy.sh --skip-db to preserve a database node, you can 
   # tell Terraform to reconnect to it instead of creating a new one.
   # create_db_node         = false
   # existing_db_private_ip = "10.0.X.Y"
   ```
   > [!NOTE]
   > **How to Generate a Django Secret Key (`django_secret_key`)**
   > This key must be identical across all App Nodes. You can quickly generate a secure, 50-character cryptographic key directly in your terminal using Python 3:
   > ```bash
   > python3 -c "import secrets; print(''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)') for i in range(50)))"
   > ```
   > Copy the output and paste it into your `terraform.tfvars` file.

   > [!NOTE]
   > **How to Generate a GitHub Token (`github_token`)**
   > If this repository is private, Terraform needs a Personal Access Token to clone the code on the EC2 instances. 
   > 1. Log in to GitHub and go to **Settings**.
   > 2. Scroll down to the bottom left and click **Developer settings**.
   > 3. Click **Personal access tokens** -> **Fine-grained tokens**.
   > 4. Click **Generate new token**.
   > 5. Give it a name (e.g., "Terraform EC2 Clone") and set an expiration.
   > 6. Under **Repository access**, choose **Only select repositories** and select this repository.
   > 7. Under **Permissions** -> **Repository permissions**, locate **Contents** and set it to **Read-only**.
   > 8. Click **Generate token** at the bottom.
   > 9. Copy the token (it starts with `github_pat_`) and paste it into your `terraform.tfvars` file.
   > 
   > *If the repository is later made public, you can leave this variable empty (`github_token = ""`) or omit it entirely.*

3. Preview the infrastructure plan:
   ```bash
   terraform plan
   ```
4. Deploy the infrastructure:
   ```bash
   terraform apply
   ```
5. Once complete, Terraform will output the **Load Balancer Public IP**. Wait about 2-3 minutes for the `user_data` scripts to finish installing Docker and booting the containers, then visit the IP in your browser!

## How to Clean Up Resources

Terraform allows you to destroy all resources it created to prevent runaway AWS costs.

### Option 1: Full Destruction
To destroy everything (VPC, Security Groups, EC2 instances, IAM roles):
```bash
terraform destroy
```

### Option 2: Targeted Destruction (Keep VPC/IAM)
If you only want to spin down the EC2 instances to save costs, but want to keep the VPC, Security Groups, and IAM roles intact so your next `terraform apply` is faster, use the included wrapper script:

```bash
chmod +x destroy.sh
./destroy.sh --skip-vpc --skip-sg --skip-iam
```
This script safely untracks the base infrastructure from Terraform's state before executing `terraform destroy`.
