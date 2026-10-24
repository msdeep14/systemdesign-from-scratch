# BSES v0 - Social Media Application

This is a monolithic Django application that serves as the backend for the system. It handles user authentication, photo uploads, newsfeed generation, and interactions (likes/comments).

## API Reference
TrueCourse relies on explicit HTTP documentation to generate tests. Here are the core endpoints that can be tested:

### Authentication
- **Signup**: `POST /users/signup/`
  - Payload (Form Data): `email`, `username`, `password`
  - Success: `302 Found` (redirects on successful signup)
- **Login**: `POST /users/login/`
  - Payload (Form Data): `username`, `password`
  - Success: `200 OK` (establishes an authenticated session)

### Photos
- **Upload Photo**: `POST /photos/upload/`
  - Payload (Multipart Form): `image` (file), `caption` (text)
  - Success: `302 Found` (redirects to the uploaded photo or home page)

### Newsfeed
- **Generate Newsfeed**: `GET /`
  - Success: `200 OK` (returns the chronological feed of photos)

## Features

- **User Accounts**: Custom signup flow using hidden UUID usernames for system stability and explicit display usernames for URLs. Follow/unfollow functionality.
- **Photos**: Upload photos (auto-compressed to enforce 2MB limits), like, and comment.
- **Newsfeed**: Paginated global feed merging followed users' posts and community posts.
- **Communities**: Create and join niche communities. Upload photos exclusively to a community context. Invite other members.
- **Notifications**: Centralized alerts for community invites, photo likes, and comments.

## Local Development Setup

1. **Clone and create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # dev tools: ruff, pylint, pre-commit
   ```

3. **Start PostgreSQL Database**:
   The application strictly enforces PostgreSQL. Start the background database container:
   ```bash
   docker-compose up -d db
   ```

4. **Run migrations**:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

5. **Start the Gunicorn WSGI Server**:
   Instead of the Django development server, run the production Gunicorn server locally:
   ```bash
   gunicorn --bind 0.0.0.0:8000 --workers 3 bses.wsgi:application
   ```
   Visit `http://localhost:8000` in your browser.

## Start the Decoupled Architecture Locally via Docker
To run the full decoupled system locally (mimicking the production environment without AWS-specific networking), use the provided local `docker-compose.yml`. This boots the PostgreSQL database, multiple Django Gunicorn workers, and the Nginx Load Balancer:

```bash
docker compose up -d --build
```
You can then visit `http://localhost` in your browser. Nginx will route your requests to the application workers.

To stop the cluster:
```bash
docker compose down
```

## Redis Sentinel Deployment (Local)

The local environment supports a high-availability Redis Sentinel cluster (1 Primary, 3 Replicas, 3 Sentinels).

### Start Sentinel Cluster with Application
```bash
# Remove any legacy standalone container and start stack
docker rm -f photoz-redis-1 2>/dev/null || true
docker compose up -d --remove-orphans
```

### Start Sentinel Cluster Only
```bash
# Run only Redis Primary, Replicas, and Sentinels
docker compose -f docker-compose-redis-sentinel.yml up -d
```

### Check Cluster Status
```bash
docker exec photoz-sentinel-1 redis-cli -p 26379 sentinel master mymaster
```

### Test Automated Failover
```bash
# Runs primary pause, failover promotion, and replica auto-discovery test
./scripts/test_sentinel_failover.sh
```

### Switch to Standalone Redis
```bash
# 1. Stop Sentinel cluster
docker compose down

# 2. Start standalone Redis container
docker run -d --name photoz-redis-1 -p 6379:6379 redis:7

# 3. In .env, unset REDIS_SENTINELS and set REDIS_URL:
# REDIS_SENTINELS=""
# REDIS_URL=redis://localhost:6379/1
```

### Adding or Updating Dependencies
When you add or update dependencies in `requirements.txt`, running `docker-compose restart` will not install them because existing container images are not rebuilt. You must rebuild the images and recreate the containers:
```bash
docker compose build web consumers
docker compose up -d web consumers
```
Or rebuild the entire cluster:
```bash
docker compose up -d --build
```

### Applying Database Migrations in Docker
If you modify the Django models (`models.py`) while using the Docker setup, you must generate and apply migrations inside the running web container:
```bash
docker-compose exec web bash -c "python manage.py makemigrations && python manage.py migrate"
```

### Interacting with the Local Database
While the cluster is running, you can connect directly to the PostgreSQL database container to run queries, test indexes, or debug.

Connect to the database using `psql`:
```bash
docker-compose exec db psql -U postgres -d bses
```

You can seed the data in the database if needed:
```bash
cd photoz
source venv/bin/activate  
pip install -r requirements.txt 
cd chapter04/query_optimization 
python seed_data.py --reset 
```

Login with username `test_user` and `password123`

Once connected, you can run standard SQL queries. Here are some examples:
```sql
-- select query
select * from photos_photo limit 1;

-- Exit the database terminal
\q
```
## Code Quality

The project uses [ruff](https://docs.astral.sh/ruff/) for formatting and fast lint, and [pylint](https://pylint.readthedocs.io/) for deeper static analysis. Both are scoped to `photoz/`.

### Install pre-commit hook

Run this once after cloning:
```bash
# from repo root
pre-commit install
```

After this, ruff and pylint run automatically on every `git commit` for changed `photoz/` files. A commit is blocked if either tool reports errors.

### Run manually

All commands should be run from inside the `photoz/` directory.

**Ruff — lint:**
```bash
ruff check .
```

**Ruff — format check** (does not modify files):
```bash
ruff format --check .
```

**Ruff — auto-fix** (fixes safe issues like import order):
```bash
ruff check --fix .
ruff format .
```

**Pylint:**
```bash
pylint \
  --load-plugins=pylint_django \
  --django-settings-module=bses.settings \
  $(find . -name "*.py" -not -path "*/migrations/*" -not -path "*/venv/*")
```

### CI enforcement

The GitHub Actions `deploy.yml` runs a `lint` job on every push to `main` and `staging`. The `test` job only runs if `lint` passes, so a failing lint check blocks the full deploy pipeline.

## Architecture as Code (C4 Model & CALM)

Photoz maintains its software architecture as code using the C4 model (Structurizr) and FINOS CALM.

### 1. Structurizr (C4 Model)

The architecture is defined in `photoz/structurizr/workspace.dsl`.

#### Run and View Locally
Run the Structurizr Docker container to view the diagrams in your browser:
```bash
cd photoz
docker run -it --rm -p 8080:8080 -v $(pwd)/structurizr:/usr/local/structurizr structurizr/structurizr local
```
Open `http://localhost:8080` in your browser. Any updates made to `workspace.dsl` reflect automatically.

#### Generate Level 4 (Code / ER) Diagrams
Structurizr models Levels 1 to 3 (Context, Containers, Components). To generate an Entity-Relationship (ER) diagram directly from Django models:
```bash
cd photoz
source venv/bin/activate
python manage.py graph_models -a -o models_code_view.png
```

### 2. FINOS Architecture as Code (CALM)

The CALM architecture model is defined in `photoz/architecture/photoz.calm.json` and validated against architectural guardrails in `photoz/architecture/guardrails.pattern.json`.

#### Install CALM CLI
Install the CLI globally:
```bash
npm install -g @finos/calm-cli@latest
```

#### Validate the Architecture
To validate the architecture against the FINOS schema and guardrails:
```bash
cd photoz
calm validate -a architecture/photoz.calm.json -p architecture/guardrails.pattern.json
```
This validation also runs automatically on `git commit` via `pre-commit`.

#### Generate Architecture Documentation Site
To generate the Docusaurus documentation site with Mermaid flowchart diagrams:
```bash
cd photoz
calm docify -a architecture/photoz.calm.json -o architecture/docs

# Serve the site locally
cd architecture/docs
npm install
npm run start
```
Open `http://localhost:3000` to view the documentation site.

## Production Deployment (AWS EC2 / Docker)


For detailed deployment strategies and architectural decisions, refer to the full [EC2 Deployment Guide](skills/aws-ec2-deployment-v0.md). Below are the essential steps to launch this application on AWS.

### 1. Server Provisioning & Security
1. Launch an AWS EC2 `t3.micro` instance running **Ubuntu Server 26.04 LTS**.
2. Configure a **Security Group** to allow:
   - **SSH (Port 22)**: Restricted to your own local Public IP.
   - **HTTP (Port 80)**: Open to `0.0.0.0/0` (Anywhere IPv4).

### 2. Connect and Prepare Environment
SSH into your instance and pull the repository. Then, install Docker using the provided script:
```bash
ssh -i /path/to/your-key.pem ubuntu@<your-ec2-public-ip>

# Generate an SSH deploy key and add it to your GitHub to pull the code
ssh-keygen -t ed25519
cat ~/.ssh/id_ed25519.pub

git clone git@github.com:msdeep14/systemdesign-from-scratch.git
cd systemdesign-from-scratch/photoz

# Run the Docker installation script
chmod +x configure_dependencies.sh
bash configure_dependencies.sh

# Apply the docker group changes to your current session
newgrp docker
```

### 3. Deploying the 3-Tier Architecture
Photoz has been upgraded to a production-grade decoupled architecture featuring dynamic Service Discovery! The monolithic `docker-compose.yml` has been shattered into three role-specific files:
1. `docker-compose-db.yml` (Postgres only)
2. `docker-compose-app.yml` (Django Workers + Consul Agent)
3. `docker-compose-lb.yml` (Nginx Router + Consul Server + Consul Template)

This architecture allows the Load Balancer to instantly and automatically detect when new App Nodes are spun up or destroyed.

**For complete step-by-step instructions on deploying this architecture across multiple EC2 instances using Terraform, please read:**
👉 [../chapter03/iaac/terraform/README.md](../chapter03/iaac/terraform/README.md)
