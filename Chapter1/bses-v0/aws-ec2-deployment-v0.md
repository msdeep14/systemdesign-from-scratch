# EC2 Production Deployment Guide

## 1. Instance Launch Specifications
Deploy the BSES Django application to the most cost-effective AWS EC2 machine (Free Tier eligible).

- **Instance Type:** `t3.micro` (or `t2.micro` depending on region availability).
- **Amazon Machine Image (AMI):** Ubuntu Server 24.04 LTS (HVM), SSD Volume Type.
- **Storage:** 8 GB General Purpose SSD (gp2/gp3) is sufficient.

## 2. Security Configuration (AWS Console)
Before launching the instance, you must create or attach a Security Group with the following strictly defined inbound rules:

1. **SSH Access (Port 22)**
   - Type: SSH
   - Source: Custom -> `59.99.189.135/32` *(Your current local machine's public IP)*
   - *This ensures only your specific machine can manage the server remotely.*

2. **Web Traffic (Port 80)**
   - Type: HTTP
   - Source: Anywhere IPv4 -> `0.0.0.0/0`
   - *This exposes the Docker-Compose mapped web application to the public internet.*

## 3. Server Management via SSH
Once the EC2 instance is running and you have downloaded your `.pem` key pair from AWS, configure your key permissions and access the server:
```bash
# Secure your private key (required by AWS)
chmod 400 your-key-pair.pem

# Connect to the instance
ssh -i /path/to/your-key-pair.pem ubuntu@<your-ec2-public-ip>
```

## 4. Server Provisioning & Application Launch
Once connected via SSH, run the following commands sequentially on the EC2 machine to install Docker, pull your codebase, and launch the application.

### A. Install Docker & Docker Compose
```bash
sudo apt update
sudo apt install -y docker.io
sudo snap install docker
sudo usermod -aG docker ubuntu

# Switch to the new group to avoid needing 'sudo' for docker commands in this session
newgrp docker
```

### B. Generate SSH Deploy Key (For GitHub Access)
Since the repository is hosted on GitHub, generate a secure SSH key on the EC2 machine to pull the code:
```bash
ssh-keygen -t ed25519 -C "ec2-deploy-key"

# Print the public key to the console
cat ~/.ssh/id_ed25519.pub
```
*Action:* Copy the printed key and add it to your GitHub repository's **"Deploy Keys"** (Settings -> Deploy keys -> Add deploy key).

### C. Clone and Run the Application
```bash
# Clone the repository
git clone git@github.com:msdeep14/bses-v0.git
cd bses-v0

# Start the production cluster (Database + Django/Gunicorn via Port 80)
docker-compose up -d --build
```

## 5. Verification
Open a web browser and navigate directly to your EC2 instance's Public IPv4 Address:
```text
http://<your-ec2-public-ip>
```
The application should load immediately without specifying any port.
