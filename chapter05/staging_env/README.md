# Staging Environment Deployment Guide

This project uses **Terraform Workspaces** to manage the `staging` environment. Workspaces allow you to provision an entirely separate infrastructure stack (VPC, EC2 instances, S3 buckets) using the exact same Terraform code, without impacting `production`.

## 1. Apply Production Updates
Before creating the staging environment, you must apply the recent Terraform changes to your existing production (`default`) workspace to tag resources and provision the production IAM user.

```bash
cd iaac/aws/terraform
terraform workspace select default
terraform apply
```

## 2. Deploy Staging Environment
Switch to a new `staging` workspace. Terraform will create a fresh, isolated state file.

```bash
terraform workspace new staging
```

*(Optional)* Create a `staging.tfvars` file if you want to use smaller instance types to save costs (e.g., `t3.micro`).

Deploy the staging infrastructure:
```bash
terraform apply -var-file=staging.tfvars
```
*Note: Terraform will automatically provision a new suffixed S3 bucket (e.g., `your-bucket-staging`) for media storage during this step.*

## 3. Retrieve Deployment Credentials
The Terraform code dynamically creates deployment IAM users based on the active workspace.
1. Log in to the **AWS Console**.
2. Navigate to **IAM > Users**.
3. Locate `prod-user` and `staging-user`.
4. Generate **Access Keys** for these users to be used in your CI/CD pipelines or local deployment scripts.

### Configure GitHub Secrets for Staging
Since Staging uses a completely separate set of SSH keys, you must provide the Staging App Node's private SSH key to GitHub Actions.
1. Copy the contents of the `.pem` file for the `photoz-app-key-staging` key pair you created in AWS.
2. In your GitHub repository, go to **Settings > Secrets and variables > Actions**.
3. Create a new repository secret named `APP_NODE_SSH_KEY_STAGING` and paste the `.pem` contents.
*(The pipeline automatically switches between `APP_NODE_SSH_KEY` and `APP_NODE_SSH_KEY_STAGING` based on the branch being deployed!)*

## Teardown (Staging Only)
If you ever want to destroy the staging environment to save costs:
```bash
terraform workspace select staging
terraform destroy -var-file=staging.tfvars
```
**CRITICAL:** Always verify you are in the `staging` workspace (`terraform workspace show`) before running destroy!

> [!NOTE]
> **GitHub Runner Token Expiration:** If you tear down the environment and want to provision it again later, you must generate a **new** GitHub Runner Registration token and update your `staging.tfvars` file. The registration token from the GitHub UI expires after **1 hour**. 
> *(This expiration only affects the initial provisioning/registration step. Once the runner registers successfully, it is granted long-lived internal credentials and will continue to work indefinitely until you destroy it).*

## Troubleshooting

### Error: VcpuLimitExceeded
```
Error: creating EC2 Instance: operation error EC2: RunInstances ... api error VcpuLimitExceeded: You have requested more vCPU capacity than your current vCPU limit of 16 allows...
```
**Cause:** New AWS accounts typically have a hard limit of 16 vCPUs for standard On-Demand instances. A fully scaled `production` environment easily consumes 14 vCPUs (7 instances running on `t3.micro` which are 2 vCPUs each). Attempting to deploy `staging` concurrently will exceed the 16 vCPU limit.

**Solution:**
1. Log in to the AWS Console.
2. Search for and navigate to **Service Quotas**.
3. In the left sidebar, click **AWS services** -> **Amazon Elastic Compute Cloud (Amazon EC2)**.
4. Search for `Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances`.
5. Select it and click **Request quota increase**.
6. Enter a new value (e.g., `32`) and submit. AWS typically approves this automatically within an hour.
