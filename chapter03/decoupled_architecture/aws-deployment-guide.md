# AWS Deployment Guide

This guide details the steps required to deploy the fully decoupled, 3-tier production architecture for the Photoz application on AWS.

## Horizontal Scaling in New Architecture

To transition from a single-node deployment to a true horizontally scalable architecture, you must provision multiple EC2 instances and distribute the Docker containers across them. 

### Architecture Overview
- **Node 1 (Database):** Runs the PostgreSQL container (`docker-compose-db.yml`).
- **Node 2 & 3 (App Servers):** Run the Django application containers (`docker-compose-app.yml`).
- **Node 4 (Load Balancer):** Runs the Nginx proxy container (`docker-compose-lb.yml`).

### Prerequisites
1. Provision the EC2 instances in your AWS Console (e.g., Ubuntu 26.04, `t3.micro`).
2. **IAM Role (Crucial):** Create an IAM Role with `CloudWatchLogsFullAccess` and attach it to your App Server and Load Balancer EC2 instances. Docker requires this to stream logs to AWS.
3. Ensure they are in the same VPC so they can communicate via Private IPv4 addresses.
4. Install Docker and Docker Compose on all instances using the `configure_dependencies.sh` script provided in this repository. This script will also automatically generate a template `.env` file in your directory.

### Step 1: Configure Security Groups
Proper network isolation is the most critical part of a decoupled architecture.
*   **Database Node:** Allow inbound TCP `5432` **only** from the Private IPs of the App Nodes. Do not open to `0.0.0.0/0`.
*   **App Nodes:** Allow inbound TCP `8000` **only** from the Private IP of the Load Balancer Node.
*   **Load Balancer Node:** Allow inbound TCP `80` (HTTP) from `0.0.0.0/0` (The Internet).

### Step 2: Deploy the Database
1. SSH into the Database EC2 instance.
2. Clone or copy the repository.
3. Edit the auto-generated `.env` file in the `photoz/` directory and populate the placeholders for `POSTGRES_PASSWORD`.
4. Run the database container:
   ```bash
   docker compose -f docker-compose-db.yml up -d
   ```
5. Note the **Private IPv4 Address** of this instance.

### Step 3: Deploy the App Servers
1. SSH into your first App Server EC2 instance.
2. Clone or copy the repository.
3. Edit the auto-generated `.env` file in the `photoz/` directory. Populate all required secrets and replace the `<INSERT_DATABASE_EC2_PRIVATE_IP>` placeholder for `POSTGRES_HOST` with the Private IP from Step 2.
4. Run the app container:
   ```bash
   docker compose -f docker-compose-app.yml up -d --build
   ```
5. Repeat these steps for all additional App Server instances you wish to provision. Note their Private IPs.

### Step 4: Deploy the Load Balancer
1. SSH into the Load Balancer EC2 instance.
2. Clone or copy the repository.
3. Edit `photoz/nginx/nginx.conf`. In the `upstream photoz_web` block, replace the `<INSERT_APP_NODE_X_PRIVATE_IP>` placeholders with the Private IPs of your App Servers from Step 3.
4. Run the proxy container:
   ```bash
   docker compose -f docker-compose-lb.yml up -d --build
   ```

### Step 5: Verification
1. Access the Public IPv4 Address or Public DNS of your **Load Balancer Node** in a web browser.
2. You should see the Photoz application running.
3. To verify load distribution, check the logs of your App Servers while generating traffic:
   ```bash
   docker logs -f photoz-web-1
   ```
   You will see traffic alternating between the different App Nodes as Nginx applies its default round-robin load balancing strategy.
