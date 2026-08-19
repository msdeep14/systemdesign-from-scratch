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
*Note: S3 Buckets and deployment IAM users are deliberately NOT tracked by Terraform to prevent accidental data deletion or cross-environment credential leakage during teardowns.*

## 3. Manual S3 and IAM Setup (One-Time)
Since stateful resources (S3 buckets and IAM users) are not managed by Terraform, you must create them manually for the new environment.

### A. Create the S3 Bucket

<details>
<summary><b>Option 1: Using AWS CLI (Recommended)</b></summary>

**Create the bucket:**
```bash
aws s3api create-bucket --bucket bses-v0-s3-storage-staging --region ap-south-1 --create-bucket-configuration LocationConstraint=ap-south-1
```
*(Note: Remove the LocationConstraint if you are deploying to us-east-1)*

**Delete the bucket (Cleanup):**
```bash
aws s3 rb s3://bses-v0-s3-storage-staging --force
```

</details>

<details>
<summary><b>Option 2: Using AWS Console (UI)</b></summary>

1. Log in to the AWS Console and go to **S3 > Create bucket**.
2. Name the bucket (e.g., `bses-v0-s3-storage-staging`).
3. Leave Block Public Access **ON** (CloudFront uses Origin Access Control to read the bucket securely).
3. Leave all other settings default and click **Create bucket**.

*(Note: We no longer need to create IAM Users for deployments! We use OIDC.)*

## 4. Configure GitHub Secrets for Staging
Since Staging uses a completely separate set of infrastructure, you need to configure the following secrets in GitHub (**Settings > Secrets and variables > Actions**):

1. **`APP_NODE_SSH_KEY_STAGING`**: Copy the contents of the `.pem` file for the `photoz-app-key-staging` key pair you created in AWS. *(The pipeline automatically switches between `APP_NODE_SSH_KEY` and `APP_NODE_SSH_KEY_STAGING` based on the branch being deployed!)*
2. **`AWS_ROLE_<YOUR_USERNAME>`**: Because we use OIDC for the scheduled start/stop workflow, you need to provide the Role ARN that Terraform provisioned for you. Look in your AWS Console under IAM Roles for `github-actions-deployer-role-staging` and copy its ARN. Save it as a GitHub Secret appending your exact GitHub username, e.g., `AWS_ROLE_MSDEEP14`.

### How GitHub knows which runner to invoke
Our deployment workflow (`.github/workflows/deploy.yml`) is configured to conditionally choose a runner using labels:
- If pushing to the `main` branch, the workflow specifies `runs-on: [self-hosted, prod]`.
- If pushing to the `staging` branch, the workflow specifies `runs-on: [self-hosted, staging]`.

When Terraform provisions the GitHub Runner EC2 instance, it automatically registers the runner with GitHub using the `local.runner_label` (which evaluates to `staging` in the staging workspace). This ensures GitHub sends the staging deployment job to the isolated staging runner.

## Teardown (Staging Only)
If you ever want to destroy the staging environment to save costs:
```bash
terraform workspace select staging
./destroy.sh
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
