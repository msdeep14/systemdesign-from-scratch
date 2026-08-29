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


### Phase: Implement Private Self-Hosted Runners for CI/CD (Date: 2026-08-16, Commit: 247f42b6ce84b04e46f92132d33ec15295436775, Model: Gemini 3.1 Pro (High))
- **Analysis**: Running deployment commands directly from public GitHub runners requires exposing SSH ports to the internet (or dynamic whitelisting) and storing long-lived credentials in GitHub Secrets. To enhance security, we migrated to a self-hosted runner located within the private AWS VPC, avoiding public IP exposure.
- **Actions Taken**:
  - Updated `variables.tf` with a new sensitive variable `github_runner_token` to hold the runner registration token.
  - Updated `security.tf` to create a new security group for the runner (no inbound ports required, outbound to internet allowed) and allowed SSH on the `app` nodes exclusively from the runner's security group.
  - Updated `main.tf` to provision an EC2 instance (`aws_instance.github_runner`) that automatically installs dependencies (Docker, Python, PostgreSQL client), downloads the GitHub Actions runner, registers itself, and starts the service via `user_data`.
  - Updated `.github/workflows/deploy.yml` to change the deployment jobs to `runs-on: self-hosted`, removed the dynamic IP whitelisting logic, and updated the SSH connection to use the `PrivateIpAddress` of the app node instead of the `PublicIpAddress`.
  - Updated `chapter05/deployment_automation/README.md` with instructions on how to obtain and provide the runner token.


### Phase: Eliminate AWS Credentials from GitHub (Date: 2026-08-16, Commit: 247f42b6ce84b04e46f92132d33ec15295436775, Model: Gemini 3.1 Pro (High))
- **Analysis**: After implementing self-hosted runners, the GitHub Action workflow still required static AWS Access Keys in GitHub Secrets just to trigger the instance refresh and fetch the app node IP. Since the runner is an EC2 instance, it is a security best practice to rely entirely on its IAM Instance Profile instead of passing static credentials.
- **Actions Taken**:
  - Updated `iam.tf` to create a new policy (`runner-deploy-access`) granting the `photoz-ec2-role` permissions for `ec2:DescribeInstances` and `autoscaling:StartInstanceRefresh`.
  - Updated `.github/workflows/deploy.yml` to completely remove the `aws-actions/configure-aws-credentials` steps.
  - Added `AWS_DEFAULT_REGION` to the workflow jobs via the remaining `AWS_REGION` secret so the AWS CLI can route API calls correctly.
  - Refactored `chapter05/deployment_automation/README.md` to remove the AWS access keys from the required secrets list.


### Phase: Segregate SSH Keys by Architectural Tier (Date: 2026-08-16, Commit: 247f42b6ce84b04e46f92132d33ec15295436775, Model: Gemini 3.1 Pro (High))
- **Analysis**: Using a single SSH key across all instances creates a massive blast radius. A compromise of the GitHub Actions pipeline (which only needs app node access) would grant access to the entire data tier. To adhere to the Principle of Least Privilege, we separated the keys by tier (app, db/redis, lb, runner). To prevent Terraform from destroying existing stateful instances during rotation, we added `lifecycle { ignore_changes = [key_name] }`.
- **Actions Taken**:
  - Updated `variables.tf` to replace the single `key_name` with `app_key_name`, `db_key_name`, `lb_key_name`, and `runner_key_name`.
  - Updated `main.tf` to assign the respective keys to the correct AWS instances.
  - Added `lifecycle { ignore_changes = [key_name] }` to the DB, Redis, and LB instances in `main.tf` to allow safe, manual key rotation on existing instances without causing a destructive recreation.
  - Updated `chapter05/deployment_automation/README.md` to clarify that the `APP_NODE_SSH_KEY` secret is strictly for the app tier.


### Phase: Fix AWS CLI missing on GitHub Runner (Date: 2026-08-16, Commit: 247f42b6ce84b04e46f92132d33ec15295436775, Model: Gemini 3.1 Pro (High))
- **Analysis**: The pipeline failed with `aws: command not found`. The self-hosted runner EC2 instance did not have the AWS CLI installed, which is required to fetch the app node IP and trigger the ASG instance refresh. 
- **Actions Taken**:
  - Updated `aws_instance.github_runner` in `main.tf` to include `awscli` and `unzip` in the `apt-get install` user data script.


### Phase: Fix GitHub Runner Dependencies and SSH (Date: 2026-08-16, Commit: 58c0c423906ac0456493fd61d42695facf73f0d8, Model: Gemini 3.1 Pro (High))
- **Analysis**: The runner was failing to register with GitHub and the user was unable to SSH in to debug it. The registration failure was caused by missing .NET Core dependencies which are required by the GitHub Runner's `./config.sh` script. The SSH failure was due to the runner's Security Group having no inbound rules.
- **Actions Taken**:
  - Updated `main.tf` to run `./bin/installdependencies.sh` as root before executing `./config.sh` to ensure all required libraries (like `libicu`) are installed.
  - Updated `security.tf` to add an ingress rule for port 22 from the developer's IP to the `photoz-github-runner-sg` to allow SSH access for troubleshooting.

### Phase: Staging Environment Support (Date: 2026-08-16, Commit: [ce38385dc165018f967a6244337d44d51aaf3b7e], Model: Gemini 3.1 Pro (High))
- **Analysis**: Introduced Terraform workspaces to support a staging environment alongside production.
- **Actions Taken**:
  - Added `env_suffix` and `s3_bucket_name` to `locals` in `main.tf` to conditionally append the workspace name to resources.
  - Added `default_tags` block to the AWS Provider in `provider.tf` to tag all resources with `Environment = staging/prod`.
  - Modified resource names and tags across `iam.tf`, `security.tf`, `main.tf`, `network.tf`, `cloudwatch.tf`, and `cloudfront.tf` to append `${local.env_suffix}`.
  - Modified `aws_s3_bucket_policy` to accept suffixed bucket names to restrict access to correct environment bucket.
  - Updated Django `.env` injection in `user_data` of EC2 instances to use `local.s3_bucket_name`.
  - Added `aws_iam_user` resource to create workspace-specific deployment users (`prod-user` or `staging-user`).
  - Conditionally created `aws_s3_bucket.photoz_storage` in `main.tf` to automatically provision the S3 bucket for non-default workspaces, while leaving the manual production bucket untouched.
  - Validated configuration with `terraform validate`.

### Phase: CI/CD Branch Environments (Date: 2026-08-16, Commit: [ce38385dc165018f967a6244337d44d51aaf3b7e], Model: Gemini 3.1 Pro)
- **Analysis**: The `deploy.yml` file was hardcoded for the `main` branch and production resources, making it impossible to automatically deploy changes to the staging environment without manually modifying the pipeline file. Additionally, if multiple runners exist, GitHub randomly assigns jobs unless specific labels are used.
- **Actions Taken**:
  - Updated `main.tf` to assign dynamic labels (`prod` or `staging`) to the GitHub Runner registration command (`./config.sh --labels ...`) based on the Terraform workspace.
  - Refactored `.github/workflows/deploy.yml` to trigger on both `main` and `staging` branches.
  - Updated `deploy.yml` to dynamically select the runner label, target ASG name, SSH Key secret (`APP_NODE_SSH_KEY` vs `APP_NODE_SSH_KEY_STAGING`), and `git pull` branch based on `${{ github.ref_name }}`.
  - Updated `chapter05/staging_env/README.md` to instruct the developer to add the new staging SSH key to GitHub Secrets.
  - Manually creating the S3 bucket and IAM user is a pain point, but it ensures that we don't lose the S3 bucket and IAM user upon every teardown.  [commit - b931735d02265e00c422d404bf6cda083c82463e]

### Phase: OIDC Integration and Automated Sleep/Wake Cycle (Date: 2026-08-19, Commit: 68383de13a944a16e9f0e23f8523be0f1b6998f4, Model: Gemini 3.1 Pro(High) )
* **Analysis**: Relying on long-lived IAM user access keys is a security risk, and keeping the staging environment running 24/7 incurs unnecessary compute costs. We decided to implement OpenID Connect (OIDC) between AWS and GitHub Actions. This allows GitHub to securely assume an AWS IAM role dynamically. Furthermore, we hard-locked this role to only trust workflows triggered by the `msdeep14` user, providing absolute security even in a public repository. We then used this OIDC integration to power a new scheduled workflow that automatically stops all compute resources (ASG, DB, Redis, LB) at night and starts them in the morning, all running on a free `ubuntu-latest` runner.
* **Actions Taken**:
  - Configured `aws_iam_openid_connect_provider` in `iaac/aws/terraform/iam.tf` for GitHub Actions.
  - Created `aws_iam_role.github_actions_deployer` with a trust policy enforcing `token.actions.githubusercontent.com:sub = repo:msdeep14/systemdesign-from-scratch:*` and `token.actions.githubusercontent.com:actor = msdeep14`.
  - Created `.github/workflows/schedule-staging.yml` using `ubuntu-latest` to schedule a sleep (scale down ASG, stop static EC2s) and wake cycle using AWS CLI.
  - Used dynamic secret resolution in the workflow (`role-to-assume: $\{ { secrets[format('AWS_ROLE_{0}', github.actor)] } }`) to enforce multi-account isolation if other users fork or push to the repo.

### Phase: Systems Manager (SSM) Migration (Date: 2026-08-19, Commit: N/A, Model: Gemini 3.1 Pro(High) )
* **Analysis**: Having a dedicated self-hosted EC2 instance for GitHub Runners adds unnecessary cost and complexity. Additionally, requiring SSH (port 22) to be open on the application nodes for database migrations is a security risk. By switching to AWS Systems Manager (SSM) Run Command and OIDC, we can run the database migration directly on the application nodes from standard GitHub-hosted `ubuntu-latest` runners, eliminating the self-hosted runner and closing port 22 entirely.
* **Actions Taken**:
  - Attached `AmazonSSMManagedInstanceCore` policy to the `photoz_ec2_role` in `iam.tf` so the EC2 nodes can securely communicate with the SSM service.
  - Removed the `github_runner` EC2 instance, its Security Group, and related variables (`github_runner_token`, `runner_key_name`) from Terraform (`main.tf`, `security.tf`, `variables.tf`, `.tfvars`).
  - Removed the SSH ingress rule from the App Node security group in `security.tf`.
  - Refactored `.github/workflows/deploy.yml` to run on `ubuntu-latest`, authenticate via OIDC, and use `aws ssm send-command` to trigger the Django migration on one of the ASG instances.
  - Updated `chapter05/staging_env/README.md` to remove SSH key configuration steps and document that the local `.env` setup still requires IAM user credentials, even though CI/CD is now purely OIDC-based.

### Phase: IaC Automation and Remote State (Date: 2026-08-22, Commit: a3ae0bf4f3c7a5b055c98ed8f14fa4ead0cddd82, Model: Gemini 3.1 Pro (High))
* **Analysis**: As infrastructure changes become more complex, applying Terraform from local laptops poses significant risks (state file corruption, concurrent applies, missing reviews). We migrated to a remote Terraform state and a CI/CD-driven workflow for infrastructure changes to enforce strict peer review and consistency.
* **Actions Taken**:
  - Created `iaac/aws/terraform/backend.tf` to configure S3 as the remote backend. Leveraged the new native S3 locking feature (`use_lockfile = true`) introduced in Terraform 1.10+, eliminating the need for a DynamoDB lock table.
  - Authored a new GitHub Actions workflow `.github/workflows/infra.yml` that automatically formats, validates, and plans Terraform changes on Pull Requests. It also auto-applies changes on merges to the `main` branch.
  - Created `chapter05/iac_automation/README.md` to document the new infrastructure workflow, explain the necessity of manual state bucket creation, and detail how GitHub Secrets (`TF_VARS`) inject sensitive variables securely into the pipeline.
  - Removed all AWS Access Keys from the codebase and `terraform.tfvars`, pivoting entirely to EC2 IAM Instance Profiles and GitHub Actions OIDC to retrieve credentials at runtime.
  - Implemented dynamic GitHub PAT fetching for private repositories via AWS SSM Parameter Store (`/photoz/github_token`) directly in the EC2 `user_data` script, preventing the PAT from being exposed in Terraform state or EC2 instance metadata.
  - **Refactored Secrets Management:** Transitioned from AWS SSM Parameter Store to an S3 Object Storage approach for all application secrets (`github_token`, `django_secret_key`, `db_password`). Provisioned `aws_s3_bucket.secrets` in Terraform, assigned an `s3:GetObject` IAM policy to EC2, and updated all `user_data` boot scripts to pull and source `s3://photoz-secrets-ap-south-1/secrets.env` at runtime. Completely removed sensitive variables from Terraform state.
  - **Enhanced CI/CD for Multi-Environment:** Updated `.github/workflows/infra.yml` to support a two-stage promotion workflow. The pipeline now dynamically selects the Terraform workspace based on the target branch: pulling/pushing to `staging` maps to the `staging` workspace, and pulling/pushing to `main` maps to the `default` (production) workspace.
  - **Decoupled CI/CD Identity:** Removed all CI/CD IAM Roles and GitHub Actions OIDC providers from Terraform management (`iam.tf`) to prevent self-deletion during a `terraform destroy`. Provided a manual AWS CLI bootstrapping script in the README using AWS managed service-level policies for strict least-privilege access.
  - **Added Remote Destroy:** Created `.github/workflows/destroy.yml` to allow engineers to trigger a manual `terraform destroy` against any workspace directly from the GitHub UI using OIDC authentication.

### Phase: Architecture Guardrails - Structurizr C4 Model (Date: 2026-08-23, Commit: Pending, Model: Gemini 3.1 Pro(High) )
* **Analysis**: The project needs a "ground truth" architectural reference to serve as a baseline for drift detection. Evaluated multiple tools and selected Structurizr Lite to define the C4 architecture as code.
* **Actions Taken**:
  - Created `photoz/structurizr/workspace.dsl` modeling the User, Web App, Postgres DB, Redis Cache, and S3 system.
  - Details in `chapter05/architecture_guardrails/README.md`.

### Phase: Architecture Guardrails - Import Linter (Date: 2026-08-23, Commit: Pending, Model: Gemini 3.1 Pro(High))
* **Analysis**: To prevent spaghetti code and tight coupling between domain contexts, we need to enforce boundaries between Django apps (e.g., users, photos, newsfeed). `import-linter` provides an AST-level check to ensure these boundaries aren't crossed.
* **Actions Taken**:
  - Created `photoz/.importlinter` to strictly enforce independence between all core Django apps.
  - Configured `ignore_imports` to whitelist 8 existing legacy violations (e.g., `photos.views -> notifications.models`) so the build passes for now, but new violations are blocked.
  - Added `import-linter` as a pre-commit hook in `.pre-commit-config.yaml`.
  - Added `lint-imports` to the CI pipeline in `.github/workflows/deploy.yml` to block invalid pull requests.

### Phase: Architecture Guardrails - Drift Analyzer (Date: 2026-08-25, Commit: Pending, Model: Gemini 3.1 Pro)
* **Analysis**: While TrueCourse is powerful, it relies on AST routing decorators not present in Django (`urlpatterns`), meaning it drops most API flows. `drift-analyzer` provides native structural AST and git history analysis, perfectly detecting co-change coupling, pattern fragmentation, and novel dependencies in Django.
* **Actions Taken**:
  - Evaluated `drift-analyzer` on the `photoz/` repository, successfully discovering 44 structural issues (score 0.20, Grade B).
  - Documented `drift-analyzer` usage and installation in `chapter05/architecture_guardrails/README.md`.
  - Created `.github/workflows/drift.yml` to run the `mick-gsk/drift` action on PRs affecting `photoz/**` and fail on `high` severity findings.

### Phase: Architecture Guardrails - FINOS CALM Evaluation (Date: 2026-08-26, Commit: Pending, Model: Gemini 3.1 Pro High)
* **Analysis**: Evaluated FINOS Architecture as Code (CALM) and its CALMGuard tool as an alternative for detecting architectural drift. While CALM is a robust standard for "Architecture as Code", it focuses heavily on regulatory compliance (SOX, PCI-DSS, NIST) and infrastructure generation (Terraform/CI). Its "drift detection" compares the `.calm.json` model against live cloud infrastructure (AWS/GCP), rather than analyzing source code AST or git history. It requires manual maintenance of a `.calm.json` file and does not detect code-level boundary violations (e.g., tight coupling between Django apps). Therefore, it serves a different, more enterprise-compliance-focused purpose compared to `drift-analyzer` or `import-linter`.
* **Actions Taken**:
  - Cloned and reviewed the `finos/architecture-as-code` repository.
  - Analyzed `calm-guard` documentation and its approach to architectural drift and DevSecOps.
### Phase: Architecture Guardrails - FINOS CALM Integration (Date: 2026-08-26, Commit: Pending, Model: Gemini 3.1 Pro High)
* **Analysis**: Following the evaluation of FINOS CALM, we decided to adopt it in tandem with `drift-analyzer`. CALM provides a machine-readable JSON specification of the infrastructure architecture that can be used for compliance and DevSecOps validations, serving as a complement to `drift-analyzer`'s code-level AST checks.
* **Actions Taken**:
  - Created `photoz/architecture/photoz.calm.json` defining the high-level infrastructure components (Load Balancer, Web App, Primary DB, Replica DB, Cache, CDN, S3) and their relationships based on the Structurizr model.
  - Created `.github/workflows/calm-validation.yml` to automatically validate the architecture model using the `@finos/calm-cli` on push and pull requests to the `main` branch.  
### Phase: Architecture Evaluation for New Features (Date: 2026-08-27, Commit: Pending, Model: Gemini 3.1 Pro (High))
* **Analysis**: Evaluated the integration of four new features (User Tagging, Stories, Verified Profiles, Profile Links) into the current Photoz architecture. Used  and  to assess current coupling. Found that the system is a tightly coupled monolith where Django apps (, , , ) directly import each other's models inside views.
* **Decisions**: 
  * The system is too coupled for a direct microservices extraction. We must first enforce strict boundaries (Modular Monolith) by introducing an internal API/Service layer and using Event-Driven patterns (e.g., signals/Celery) instead of direct cross-app view imports.
  * Verified Profiles and Profile Links fit natively into  without adding coupling.
  * Tagging users and Stories will require service-level boundaries to prevent worsening the  violations.
* **Actions Taken**:
  * Generated Implementation Plan artifact detailing the proposed architecture adjustments and feature implementations.

### Phase: Architecture Evaluation for New Features (Date: 2026-08-27, Commit: Pending, Model: Gemini 3.1 Pro (High))
* **Analysis**: Evaluated the integration of four new features (User Tagging, Stories, Verified Profiles, Profile Links) into the current Photoz architecture. Used drift-analyzer and import-linter to assess current coupling. Found that the system is a tightly coupled monolith where Django apps (newsfeed, photos, communities, users) directly import each other's models inside views.
* **Decisions**:
  * The system is too coupled for a direct microservices extraction. We must first enforce strict boundaries (Modular Monolith) by introducing an internal API/Service layer and using Event-Driven patterns (e.g., signals/Celery) instead of direct cross-app view imports.
  * Verified Profiles and Profile Links fit natively into users.models.UserProfile without adding coupling.
  * Tagging users and Stories will require service-level boundaries to prevent worsening the import-linter violations.
* **Actions Taken**:
  * Generated Implementation Plan artifact detailing the proposed architecture adjustments and feature implementations.

### Phase: Decoupling Strategy Selection (Date: 2026-08-27, Commit: Pending, Model: Gemini 3.1 Pro (High))
* **Analysis**: The user rejected introducing an external task queue (e.g., Celery) at this stage. Evaluated using native Python `async` vs Django Signals for achieving an event-driven architecture to decouple the Django apps.
* **Decisions**:
  * Rejected native Python `async`/threading due to volatility (data loss on worker restarts), risk of event-loop starvation, and incompatibility with the current synchronous Gunicorn worker architecture.
  * Chose **Django Signals** combined with **Service Layers**. This strictly decouples the codebase and resolves `import-linter` violations. While the execution time remains synchronous (adding latency to uploads), this perfectly positions the architecture for an easy transition to a real task queue later, as signal receivers can easily be converted to Celery tasks without modifying the core views.
* **Actions Taken**:
  * Updated Implementation Plan artifact to formally define the Service Layer + Signals architecture and document the trade-offs.


### Phase: Introduce Service Layers (Date: 2026-08-29, Commit: aca7a79a4e9d4cf03b0f60d4e6e265203e8a8e2f, Model: Gemini 3.1 Pro (High))

**Analysis & Rationale:**
- The application suffered from high cyclomatic complexity and cross-app coupling (e.g., `newsfeed/views.py` importing models directly from `photos`, `users`, and `communities`). 
- To resolve `import-linter` domain violations and reduce logic embedded inside view functions, we introduced the Service Layer pattern.
- This creates explicit boundaries where apps interact with other apps exclusively through dedicated `services.py` modules, abstracting away internal data queries and complex logic (like Redis caching).

**Actions Taken:**
- `[NEW]` Created `users/services.py`, `communities/services.py`, `photos/services.py`, and `newsfeed/services.py`.
- `[MODIFY]` Refactored `newsfeed/views.py` to use the new service functions for fetching photos, user details, and communities, moving the entire Redis lock & polling logic to `newsfeed/services.py`.
- `[MODIFY]` Refactored `photos/views.py` and `communities/views.py` to remove direct cross-domain model imports, replacing them with service calls.
- `[MODIFY]` Removed resolved `ignore_imports` overrides from `.importlinter` to enforce the new strict architectural boundaries.
- `[EXECUTE]` Baselined `drift-analyzer` to lock in the reduced Co-Change Coupling and Cyclomatic Complexity improvements.

### Phase: Introduce Django Signals (Date: 2026-08-29, Commit: Pending, Model: Gemini 3.1 Pro (High))

**Analysis & Rationale:**
- The architecture requires breaking cross-app dependencies to satisfy import-linter and reduce cyclomatic complexity.
- We needed to decouple the `photos` app from the `notifications` and `newsfeed` apps so that actions in `photos` (uploads, likes, comments, deletes) do not directly import logic from other domain areas.
- Django Signals provide an asynchronous-like pub/sub mechanism to cleanly sever these dependencies. The `photos` app emits signals, while the relevant apps listen and respond independently.

**Actions Taken:**
- `[NEW]` Created `photos/signals.py` defining custom signals: `photo_uploaded`, `photo_deleted`, `photo_liked`, `photo_commented`.
- `[MODIFY]` Refactored `photos/views.py` to emit signals and completely removed dependencies on `newsfeed.services` and `notifications.models`.
- `[NEW]` Created `notifications/signals.py` to listen for `photo_liked` and `photo_commented` events, generating Notification records. Modified `notifications/apps.py` to wire these receivers on startup.
- `[NEW]` Created `newsfeed/signals.py` to listen for `photo_uploaded` and `photo_deleted` events, orchestrating the Redis cache fan-out and invalidation via its local services. Modified `newsfeed/apps.py` to wire these receivers on startup.

**Edge Cases & Learnings:**
- Care was taken not to prematurely delete cache invalidation mechanisms for the CDN inside the `delete_photo` view; the `photo.delete()` operation and `invalidate_cache()` must remain synchronized in `photos/views.py`, delegating ONLY the user feed cache fan-out to the `newsfeed` signal receiver.

## Phase: Infrastructure Configuration for ALLOWED_HOSTS (Date: 2026-08-29, Commit: 807eaf114c18a95a8d059d5d3ab4409a671f4cd9, Model: Gemini 3.1 Pro (High) )
*   **Analysis:** The application used `ALLOWED_HOSTS = ["*"]`, which triggers security linters (e.g., Drift Analyzer insecure_default). Changing it directly to a local fallback (`"localhost,127.0.0.1"`) breaks production deployments where Nginx proxies traffic via the public Load Balancer IP/Domain.
*   **Actions:**
    *   Updated `iaac/aws/terraform/main.tf` to dynamically inject the LB node's private and public IPs into the generated `.env` file for the app nodes (`ALLOWED_HOSTS=$${aws_instance.lb_node.private_ip},$${aws_instance.lb_node.public_ip},localhost,127.0.0.1`).
    *   Updated `photoz/bses/settings.py` to remove the temporary `"*"` fallback and safely rely on `os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1")`.
*   **Notes/Edge Cases:** This provides a seamless transition satisfying security linters without risking production downtime during the deployment cycle. Locally, it naturally falls back to `localhost,127.0.0.1`, enabling docker-compose local testing without any extra configuration.
