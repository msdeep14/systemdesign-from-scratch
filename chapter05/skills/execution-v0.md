# Chapter 05 Execution Log

## Phase: Deployment Automation — Step 1 (Date: 2026-08-09, Commit: Pending, Model: Gemini 3.1 Pro)

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
