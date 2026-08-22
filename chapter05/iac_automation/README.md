# Infrastructure as Code (IaC) Automation

Infrastructure code (Terraform) is structurally different from application code. A bad application deployment can typically be rolled back in minutes. A bad Terraform apply (like accidentally deleting a database) can cause data loss or extended downtime.

Because of this, Terraform changes go through CI/CD but with **stricter gates** than application code.

## Prerequisites: Bootstrapping CI/CD Identity

**CRITICAL RULE:** Terraform must NEVER manage the IAM roles and OIDC identity providers used by the CI/CD pipelines. If it did, a `terraform destroy` run from GitHub Actions would delete the very role it is using to execute, permanently severing CI/CD access to AWS.

Therefore, the CI/CD infrastructure must be created manually *once* using the AWS CLI.

Run the following script locally to bootstrap your AWS account for GitHub Actions:

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# 1. Create the State Bucket (For Terraform backend)
aws s3api create-bucket --bucket bses-v0-terraform-state --region ap-south-1 --create-bucket-configuration LocationConstraint=ap-south-1
aws s3api put-bucket-versioning --bucket bses-v0-terraform-state --versioning-configuration Status=Enabled

# 2. Create the Secrets Buckets (For EC2 bootstrapping)
aws s3api create-bucket --bucket photoz-secrets-ap-south-1-staging --region ap-south-1 --create-bucket-configuration LocationConstraint=ap-south-1

aws s3api put-bucket-versioning --bucket photoz-secrets-ap-south-1-staging --versioning-configuration Status=Enabled

# production
aws s3api create-bucket --bucket photoz-secrets-ap-south-1 --region ap-south-1 --create-bucket-configuration LocationConstraint=ap-south-1

aws s3api put-bucket-versioning --bucket photoz-secrets-ap-south-1 --versioning-configuration Status=Enabled

# create the file and upload it to S3. Replace the placeholders with your actual secrets.
cat << 'EOF' > secrets.env
POSTGRES_PASSWORD=your_db_password
SECRET_KEY=your_django_secret_key
GITHUB_TOKEN=your_github_token
EOF

aws s3 cp secrets.env s3://photoz-secrets-ap-south-1-staging/secrets.env

# 3. Create GitHub OIDC Provider (If not exists)
aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 || true

# 3. Create the Trust Policy for the repo
cat <<EOF > trust-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com" },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:sub": [
            "repo:msdeep14/systemdesign-from-scratch:ref:refs/heads/main",
            "repo:msdeep14/systemdesign-from-scratch:ref:refs/heads/staging",
            "repo:msdeep14/systemdesign-from-scratch:pull_request"
          ],
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        }
      }
    }
  ]
}
EOF

# 4. Create Terraform CI Role (Least Privilege via Managed Policies)
aws iam create-role --role-name github-actions-terraform-role --assume-role-policy-document file://trust-policy.json

aws iam attach-role-policy --role-name github-actions-terraform-role --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess

aws iam attach-role-policy --role-name github-actions-terraform-role --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

aws iam attach-role-policy --role-name github-actions-terraform-role --policy-arn arn:aws:iam::aws:policy/IAMFullAccess

aws iam attach-role-policy --role-name github-actions-terraform-role --policy-arn arn:aws:iam::aws:policy/CloudFrontFullAccess

aws iam attach-role-policy --role-name github-actions-terraform-role --policy-arn arn:aws:iam::aws:policy/CloudWatchFullAccess

aws iam attach-role-policy --role-name github-actions-terraform-role --policy-arn arn:aws:iam::aws:policy/AmazonSSMFullAccess

# 5. Create App Deployer Role (For SSM Deployment pipeline)
aws iam create-role --role-name github-actions-deployer-role --assume-role-policy-document file://trust-policy.json

cat <<EOF > deployer-policy.json
{
  "Version": "2012-10-17",
  "Statement": [{
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances", "ec2:StartInstances", "ec2:StopInstances",
        "autoscaling:DescribeAutoScalingGroups", "autoscaling:UpdateAutoScalingGroup", "autoscaling:StartInstanceRefresh",
        "ssm:GetParameter", "ssm:SendCommand", "ssm:GetCommandInvocation"
      ],
      "Resource": "*"
  }]
}
EOF

aws iam put-role-policy --role-name github-actions-deployer-role --policy-name DeployerPolicy --policy-document file://deployer-policy.json

# Cleanup
rm trust-policy.json deployer-policy.json
```

## GitHub Secrets Configuration (Mandatory)

After running the bootstrap script above, you must configure your GitHub Repository Secrets so the workflows can authenticate to AWS.

Go to your repository on GitHub -> **Settings** -> **Secrets and variables** -> **Actions** and add the following:

1. **`AWS_TERRAFORM_ROLE_ARN`**: The exact ARN of the `github-actions-terraform-role` you just created. (e.g. `arn:aws:iam::123456789012:role/github-actions-terraform-role`)
2. **`AWS_DEPLOYER_ROLE_ARN`**: The exact ARN of the `github-actions-deployer-role` you just created.
3. **`AWS_REGION`**: The AWS region you are deploying to (e.g. `ap-south-1`).
4. **`TF_VARS`**: The entire non-sensitive contents of your `terraform.tfvars` file.

## GitHub Security Policies (Mandatory)

To prevent accidental merges or rogue collaborators from triggering the Terraform apply via the trusted OIDC roles, you must configure the following in your GitHub Repository Settings:

### 1. Branch Protection Rules
Go to **Settings -> Branches -> Add branch protection rule**.
Create rules for `main` and `staging` with the following settings:
* **Require a pull request before merging**: Enabled
* **Require approvals**: Enabled (Set to at least 1 approval).
* **Do not allow bypassing the above settings**: Enabled (Crucial for preventing admins from bypassing).

### 2. Environment Protection Rules
Go to **Settings -> Environments -> New environment**.
Create two environments: `staging` and `production`.
* **Required reviewers**: Check this box and add yourself.
* This ensures that even if a workflow is triggered, GitHub will physically pause the CI/CD pipeline and wait for your manual approval before it runs `terraform apply` or touches the secrets.

## The CI/CD Workflow (`.github/workflows/infra.yml`)

GitHub Actions workflow:

1. **Pull Request (Plan Phase):**
   When an engineer opens a Pull Request against the `staging` or `main` branches with changes to `iaac/aws/terraform/**`:
   - `terraform fmt`, `init`, and `validate` are run.
   - The workflow dynamically selects the correct Terraform workspace (`staging` for the staging branch, `default` for the main branch).
   - `terraform plan` connects to AWS and generates an execution plan.
   - A GitHub Actions script posts the exact plan as a comment on the PR for **Human Review**.

2. **Merge (Apply Phase):**
   Once the PR is approved and merged:
   - `terraform apply -auto-approve` runs automatically against the target environment (`staging` or `default`).

### Manually Triggering Workflows (GitHub CLI)
If you are working on a non-default branch (like `staging`), the "Run workflow" button might not appear in the GitHub UI. You can easily bypass this by triggering the workflow manually via the [GitHub CLI (`gh`)](https://cli.github.com/):

```bash
# Authenticate with GitHub (if you haven't already)
gh auth login

# Trigger the Infrastructure CI/CD pipeline on the staging branch
gh workflow run infra.yml --ref staging

# Trigger the Infrastructure Destroy pipeline on the staging branch
gh workflow run destroy.yml --ref staging -f workspace=staging
```

## Remote State (S3 Native Locking)

For CI/CD to run Terraform, the state file (`terraform.tfstate`) must be accessible to the ephemeral GitHub Actions runners. It can no longer live locally on your laptop.

We have moved the state to **AWS S3 with Native Locking** via `backend.tf`.

### Why Native Locking?
Terraform 1.10+ introduced a highly requested feature: S3 native locking. By setting `use_lockfile = true` in our `backend.tf`, Terraform uses a `.tflock` file directly inside the S3 bucket to prevent concurrent runs.

### Manual Bucket Creation (One-Time Setup)

Because the S3 bucket holds the state of the infrastructure, **Terraform cannot manage its own state bucket**. If it did, running `terraform destroy` would delete the bucket and orphan all knowledge of the infrastructure!

For this reason, the state bucket is created **manually** as part of the Bootstrapping script provided at the top of this document.

After creating the bucket, you must migrate your local state to S3 (this pushes your local `terraform.tfstate` into the bucket):
```bash
cd iaac/aws/terraform
terraform init -migrate-state
```

## Secrets Management: The S3 Approach (Cloud-Agnostic)

How do you give a new server its initial secrets (like a database password, Django secret key, or GitHub token) when it boots up in an Auto Scaling Group? 

We have chosen the **S3 Object Storage Approach**. Object storage is a generic concept available on all major cloud providers (AWS S3, Google Cloud Storage, Azure Blob Storage), making this architecture highly portable.

### How it Works
1. **The Vault:** We provisioned a locked-down, versioned S3 bucket (`photoz-secrets-...`).
2. **The Secrets File:** An administrator uploads a `secrets.env` file into this bucket containing the sensitive environment variables (`POSTGRES_PASSWORD=...`, `SECRET_KEY=...`, `GITHUB_TOKEN=...`).
3. **IAM Permissions:** The EC2 instances are assigned an IAM Instance Profile that explicitly grants them `s3:GetObject` permission strictly for this bucket.
4. **Bootstrapping:** During boot, the EC2 `user_data` script runs:
   ```bash
   aws s3 cp s3://photoz-secrets-ap-south-1/secrets.env /tmp/secrets.env
   source /tmp/secrets.env
   ```
5. **Clean State:** Terraform never sees the secrets. They are completely removed from `terraform.tfvars`, meaning they never enter the plaintext Terraform state file.

### Architectural Alternatives & Tradeoffs

While we chose S3 for cloud portability, here is how it compares to the alternatives:

| Approach | Pros | Cons |
| :--- | :--- | :--- |
| **S3 Object Storage** *(Our Choice)* | Cloud-agnostic pattern. Zero operational overhead. Completely removes secrets from Terraform state and EC2 user_data. | Relies on IAM for security. Lacks granular parameter-level auditing (it's an all-or-nothing file download). |
| **AWS SSM Parameter Store + KMS** | AWS-native best practice. Free tier supports 10,000 parameters. High security with granular KMS decryption auditing per parameter. | Vendor lock-in to AWS. Requires managing individual parameters via AWS CLI/Console instead of a single `.env` file. |
| **HashiCorp Vault** | The industry gold-standard. Completely cloud-agnostic. Supports dynamic, short-lived database credentials and advanced rotation. | Extreme operational burden. Requires provisioning and maintaining a highly available cluster, backing storage, and handling complex unseal procedures. Massive overkill for a startup. |

## GitHub Secrets Configuration

To allow GitHub Actions to run the `infra.yml` workflow, we use the same OIDC role we set up for application deployments.

Because we moved all secrets to the S3 bucket, **`terraform.tfvars` no longer contains any sensitive credentials!**

You must create a new GitHub Repository Secret:
- **Name:** `TF_VARS`
- **Value:** *Paste the remaining non-sensitive contents of your local `terraform.tfvars` file here.*

During the CI run, GitHub Actions dynamically recreates the `terraform.tfvars` file from this secret before running the plan or apply.
