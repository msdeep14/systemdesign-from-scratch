# BSES v0 - Social Media Application

BSES is a modern, responsive social media web application built with Django. It features photo sharing, community creation, real-time-feel interactions (AJAX likes and comments), and a global notification system.

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
docker-compose up -d --build
```
You can then visit `http://localhost` in your browser. Nginx will route your requests to the application workers.

To stop the cluster:
```bash
docker-compose down
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
