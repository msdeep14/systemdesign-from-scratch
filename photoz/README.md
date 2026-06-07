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
chmod +x install_docker.sh
bash install_docker.sh

# Apply the docker group changes to your current session
newgrp docker
```

Generate an SSH deploy key (`ssh-keygen -t ed25519`) and add it to your GitHub repository to securely pull the code:
```bash
git git@github.com:msdeep14/systemdesign-from-scratch.git
cd systemdesign-from-scratch/chapter01/bses-v0
```

### 3. S3 Media Storage (Optional but Recommended)
To prevent media files from filling up your local EC2 disk, set up an Amazon S3 Bucket:
- Create an S3 bucket with **Block Public Access disabled**.
- Create an IAM User with S3 permissions and generate an Access Key pair.

### 4. Configure Environment Variables
Create a `.env` file on your server to securely pass secrets to Docker:
```bash
vi .env
```
Populate it with your credentials:
```env
# Database Configuration
POSTGRES_DB=bses
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_secure_password

# Django Security
SECRET_KEY="<generate-a-long-random-secret-key-here>"

# S3 Configuration (Set USE_S3=False to use local EC2 storage instead)
USE_S3=True
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key
AWS_STORAGE_BUCKET_NAME=your_bucket_name
AWS_S3_REGION_NAME=ap-south-1
```
*(Tip: Generate a secure Django key using `python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)*

### 5. Launch the Application Cluster
Start the production cluster using Gunicorn and PostgreSQL:
```bash
docker compose up -d --build
```

If you update any env variables in .env, you should restart the cluster by running `docker compose down` and `docker compose up -d --build` again.

Once running, you can access the application by navigating to your EC2 instance's Public IPv4 Address (`http://<your-ec2-public-ip>`) in your web browser. No port specification is required as it binds directly to Port 80.
