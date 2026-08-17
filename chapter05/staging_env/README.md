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

</details>

#### Automated Bucket Policy (Handled by Terraform)
You do NOT need to manually configure the S3 Bucket Policy! Even though the bucket itself is managed manually by you, our Terraform configuration is designed to automatically attach the correct bucket policy to it during deployment. 

Because the CloudFront Distribution ARN changes every time the staging environment is recreated, Terraform dynamically generates the exact JSON policy required and applies it to your manual bucket. When you tear down staging (`terraform destroy`), Terraform simply removes the policy, leaving your bucket safely intact.

### B. Create the Deployment IAM User
To adhere to the principle of least privilege, the `staging-user` should ONLY have access to `staging` resources.

<details>
<summary><b>Option 1: Using AWS CLI (Recommended)</b></summary>

**1. Create the policy:**
Save the Restrictive JSON Policy (found below) to a file named `staging-policy.json` and run:
```bash
aws iam create-policy --policy-name photoz-staging-deployer-policy --policy-document file://staging-policy.json
```
*(Copy the ARN from the output)*

**2. Create the user and attach the policy:**
```bash
aws iam create-user --user-name staging-user
aws iam attach-user-policy --user-name staging-user --policy-arn arn:aws:iam::<YOUR_ACCOUNT_ID>:policy/photoz-staging-deployer-policy
```

**3. Generate Access Keys:**
```bash
aws iam create-access-key --user-name staging-user
```
*(Store the Access Key ID and Secret Access Key securely, you will need them for GitHub Secrets!)*

**Delete the user and policy (Cleanup):**
```bash
# Replace with your actual Access Key ID
aws iam delete-access-key --user-name staging-user --access-key-id <ACCESS_KEY_ID>
aws iam detach-user-policy --user-name staging-user --policy-arn arn:aws:iam::<YOUR_ACCOUNT_ID>:policy/photoz-staging-deployer-policy
aws iam delete-user --user-name staging-user
aws iam delete-policy --policy-arn arn:aws:iam::<YOUR_ACCOUNT_ID>:policy/photoz-staging-deployer-policy
```

</details>

<details>
<summary><b>Option 2: Using AWS Console (UI)</b></summary>

1. Log in to the AWS Console and go to **IAM > Users > Create user**.
2. Name the user `staging-user`.
3. Select **Attach policies directly** and click **Create policy**.
4. Paste the Restrictive JSON Policy (found below).
5. Save the policy as `photoz-staging-deployer-policy` and attach it to the `staging-user`.
6. Generate **Access Keys** for this user to be used in your CI/CD pipelines or local `.env` files.

</details>

#### Restrictive JSON Policy
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "StagingS3Access",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::bses-v0-s3-storage-staging",
        "arn:aws:s3:::bses-v0-s3-storage-staging/*"
      ]
    }
  ]
}
```

## 4. Configure GitHub Secrets for Staging
Since Staging uses a completely separate set of SSH keys, you must provide the Staging App Node's private SSH key to GitHub Actions.
1. Copy the contents of the `.pem` file for the `photoz-app-key-staging` key pair you created in AWS.
2. In your GitHub repository, go to **Settings > Secrets and variables > Actions**.
3. Create a new repository secret named `APP_NODE_SSH_KEY_STAGING` and paste the `.pem` contents.
*(The pipeline automatically switches between `APP_NODE_SSH_KEY` and `APP_NODE_SSH_KEY_STAGING` based on the branch being deployed!)*

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
