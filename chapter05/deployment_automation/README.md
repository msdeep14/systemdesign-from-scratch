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

## How to Set Up GitHub Secrets

In the GitHub repo settings, add these secrets under Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | AWS access key with `autoscaling:StartInstanceRefresh` and `ec2:DescribeInstances` permissions |
| `AWS_SECRET_ACCESS_KEY` | Corresponding secret key |
| `AWS_REGION` | The AWS region (e.g., `us-east-1`) |
| `APP_NODE_SSH_KEY` | Private SSH key for the app node (the key pair used when provisioning via Terraform) |

## How to Trigger a Deploy

Push to `main`. The pipeline starts automatically.

To check the status of a running refresh:
```bash
aws autoscaling describe-instance-refreshes --auto-scaling-group-name photoz-app-asg
```
