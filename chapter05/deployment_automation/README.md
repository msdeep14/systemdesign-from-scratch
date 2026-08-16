# Deployment Automation

## The Problem

Every code change required:
1. SSH into each app node manually
2. Run `git pull`
3. Run `docker compose up --build`

This is too much of headache and error prone.

## Resolution

Introducing CI/CD

**1. A GitHub Actions pipeline**

Every push to `main` runs three jobs in sequence:

```
test → migrate → deploy
```

- `test`: Runs the Django test suite. If tests fail, nothing deploys.
- `migrate`: SSHes into one running app node and runs `python manage.py migrate`. Migrations run once, before any new instance starts.
- `deploy`: Calls AWS to trigger an ASG Instance Refresh — each running instance is replaced one-by-one with a fresh instance that pulls from `main`.

**2. Migrations moved out of container startup**

Previously, every container ran `python manage.py migrate` on startup. With rolling deploys this causes two problems:

- Two new instances boot simultaneously and race to run the same migration.
- Old instances are still running while new instances apply the migration. If the migration is not backwards-compatible, old instances start failing.

The migration now runs once in CI, before any new instance boots.

## How to Set Up the Self-Hosted Runner

To securely run migrations without opening SSH ports to the public internet, we use a private self-hosted GitHub runner inside our AWS VPC.

1. Go to your GitHub repository.
2. Navigate to **Settings** → **Actions** → **Runners**.
3. Click **New self-hosted runner** (choose Linux).
4. Do not run the commands shown! Just copy the **token** provided in the configure section (e.g., `AB1234C...`).
5. Open `iaac/aws/terraform/terraform.tfvars` and add the token:
   ```hcl
   github_runner_token = "YOUR_TOKEN_HERE"
   ```
6. Run `terraform apply`. The runner instance will automatically install dependencies, register itself with GitHub, and start the service.

> [!NOTE]
> **Updating the Runner Configuration:** If you ever modify the runner's startup script (`user_data` in Terraform), Terraform might update the instance in-place instead of recreating it. Because AWS only runs the `user_data` script on the *first boot* of a brand-new instance, your changes won't take effect. To force Terraform to recreate the runner and run the new script, you must explicitly mark it for destruction first by running: `terraform taint 'aws_instance.github_runner[0]'` and then running `terraform apply`.

## How to Set Up GitHub Secrets

In the GitHub repo settings, add these secrets under Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `AWS_REGION` | The AWS region (e.g., `us-east-1`) |
| `APP_NODE_SSH_KEY` | Private SSH key for the **app nodes only** (corresponds to the `app_key_name` in Terraform) |

## How to Trigger a Deploy

Push to `main`. The pipeline starts automatically.

To check the status of a running refresh:
```bash
aws autoscaling describe-instance-refreshes --auto-scaling-group-name photoz-app-asg
```
