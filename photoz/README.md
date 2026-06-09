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

## Start Everything via Docker (All-in-one)
If you don't want to start the database and Gunicorn manually as shown above, you can run everything together in one command using Docker. This will boot both the PostgreSQL database and the Django Gunicorn server simultaneously:
```bash
docker-compose up -d --build
```
You can then visit `http://localhost` (or your EC2 public IP) in your browser.

To stop the cluster:
```bash
docker-compose down
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
Photoz has been upgraded to a production-grade decoupled architecture! The monolithic `docker-compose.yml` has been shattered into three role-specific files:
1. `docker-compose-db.yml` (Postgres only)
2. `docker-compose-app.yml` (Django workers only)
3. `docker-compose-lb.yml` (Nginx Load Balancer only)

**For complete step-by-step instructions on deploying this architecture across multiple EC2 instances, please read:**
👉 [../chapter03/decoupled_architecture/aws-deployment-guide.md](../chapter03/decoupled_architecture/aws-deployment-guide.md)
