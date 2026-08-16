# Chapter 05 Execution Log

## Phase: Deployment Automation — Step 1 (Date: 2026-08-09, Commit: d8a8d41651586f270c86b7274698cb857b9390bf, Model: Gemini 3.1 Pro)

### What was done

Implemented the first step of deployment automation: GitHub Actions CI/CD pipeline + migrations moved out of container startup.

### Analysis and decisions

**Why migrate was removed from container startup:**
The current `docker-compose-app.yml` ran `POSTGRES_PORT=5432 python manage.py migrate` on every container start. With ASG Instance Refresh (rolling deploy), two new instances boot at the same time and both run migrate simultaneously. Django uses a DB-level advisory lock so only one succeeds, but the second instance is blocked until the first finishes. More critically, old instances are still serving traffic while new ones run the migration. If the migration is not backwards-compatible, old instances start failing mid-deploy. The migrate step belongs in CI, not in the container.

**The migrate step uses `POSTGRES_PORT=5432`:**
PgBouncer runs in transaction mode, which breaks Django migrations (ALTER TABLE inside a transaction causes deadlocks). The POSTGRES_PORT override bypasses PgBouncer and connects directly to PostgreSQL.

### Actions taken

- Modified `photoz/docker-compose-app.yml`: removed `POSTGRES_PORT=5432 python manage.py migrate &&` from the container startup command. Removed the stale comment about the port override.
- Created `.github/workflows/deploy.yml`: three-job pipeline (test → migrate → deploy). Test job uses a PostgreSQL 16 service container. Migrate job SSHes into one app node. Deploy job triggers ASG Instance Refresh.

### Edge cases noted

- The `migrate` job uses `docker compose run --rm web python manage.py migrate` rather than running Python directly on the host, so it uses the exact same Django environment (same image, same env_file) as the running app.
- `InstanceWarmup=120` gives each new instance 2 minutes to pass health checks before AWS moves to the next one.


### Phase: Implement Private Self-Hosted Runners for CI/CD (Date: 2026-08-16, Commit: Pending, Model: Gemini 3.1 Pro (High))
- **Analysis**: Running deployment commands directly from public GitHub runners requires exposing SSH ports to the internet (or dynamic whitelisting) and storing long-lived credentials in GitHub Secrets. To enhance security, we migrated to a self-hosted runner located within the private AWS VPC, avoiding public IP exposure.
- **Actions Taken**:
  - Updated `variables.tf` with a new sensitive variable `github_runner_token` to hold the runner registration token.
  - Updated `security.tf` to create a new security group for the runner (no inbound ports required, outbound to internet allowed) and allowed SSH on the `app` nodes exclusively from the runner's security group.
  - Updated `main.tf` to provision an EC2 instance (`aws_instance.github_runner`) that automatically installs dependencies (Docker, Python, PostgreSQL client), downloads the GitHub Actions runner, registers itself, and starts the service via `user_data`.
  - Updated `.github/workflows/deploy.yml` to change the deployment jobs to `runs-on: self-hosted`, removed the dynamic IP whitelisting logic, and updated the SSH connection to use the `PrivateIpAddress` of the app node instead of the `PublicIpAddress`.
  - Updated `chapter05/deployment_automation/README.md` with instructions on how to obtain and provide the runner token.


### Phase: Eliminate AWS Credentials from GitHub (Date: 2026-08-16, Commit: Pending, Model: Gemini 3.1 Pro (High))
- **Analysis**: After implementing self-hosted runners, the GitHub Action workflow still required static AWS Access Keys in GitHub Secrets just to trigger the instance refresh and fetch the app node IP. Since the runner is an EC2 instance, it is a security best practice to rely entirely on its IAM Instance Profile instead of passing static credentials.
- **Actions Taken**:
  - Updated `iam.tf` to create a new policy (`runner-deploy-access`) granting the `photoz-ec2-role` permissions for `ec2:DescribeInstances` and `autoscaling:StartInstanceRefresh`.
  - Updated `.github/workflows/deploy.yml` to completely remove the `aws-actions/configure-aws-credentials` steps.
  - Added `AWS_DEFAULT_REGION` to the workflow jobs via the remaining `AWS_REGION` secret so the AWS CLI can route API calls correctly.
  - Refactored `chapter05/deployment_automation/README.md` to remove the AWS access keys from the required secrets list.


### Phase: Segregate SSH Keys by Architectural Tier (Date: 2026-08-16, Commit: Pending, Model: Gemini 3.1 Pro (High))
- **Analysis**: Using a single SSH key across all instances creates a massive blast radius. A compromise of the GitHub Actions pipeline (which only needs app node access) would grant access to the entire data tier. To adhere to the Principle of Least Privilege, we separated the keys by tier (app, db/redis, lb, runner). To prevent Terraform from destroying existing stateful instances during rotation, we added `lifecycle { ignore_changes = [key_name] }`.
- **Actions Taken**:
  - Updated `variables.tf` to replace the single `key_name` with `app_key_name`, `db_key_name`, `lb_key_name`, and `runner_key_name`.
  - Updated `main.tf` to assign the respective keys to the correct AWS instances.
  - Added `lifecycle { ignore_changes = [key_name] }` to the DB, Redis, and LB instances in `main.tf` to allow safe, manual key rotation on existing instances without causing a destructive recreation.
  - Updated `chapter05/deployment_automation/README.md` to clarify that the `APP_NODE_SSH_KEY` secret is strictly for the app tier.

