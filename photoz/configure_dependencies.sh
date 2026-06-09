#!/bin/bash
set -e

echo "Starting Docker installation using the official APT repository..."

# 1. Add Docker's official GPG key:
echo "Setting up Docker's GPG key..."
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# 2. Add the repository to Apt sources:
echo "Adding Docker repository to Apt sources..."
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 3. Install the official Docker engine and Docker Compose:
echo "Installing Docker Engine and Docker Compose..."
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 4. Add the default 'ubuntu' user to the docker group:
echo "Adding 'ubuntu' user to the docker group..."
sudo usermod -aG docker ubuntu

echo "---------------------------------------------------------"
echo "Generating .env template..."
EC2_IP=$(hostname -I | awk '{print $1}')
DJANGO_SECRET_KEY=$(python3 -c "import secrets; import string; print(''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)') for i in range(50)))")

cat <<EOF > .env
POSTGRES_DB=bses
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<INSERT_DATABASE_PASSWORD>
USE_S3=True
AWS_STORAGE_BUCKET_NAME=<INSERT_BUCKET_NAME>
AWS_S3_REGION_NAME=ap-south-1
AWS_REGION=ap-south-1
DEBUG_MODE=False
AWS_ACCESS_KEY_ID=<INSERT_ACCESS_KEY_ID>
AWS_SECRET_ACCESS_KEY=<INSERT_SECRET_ACCESS_KEY>
SECRET_KEY=$DJANGO_SECRET_KEY
POSTGRES_HOST=<INSERT_DATABASE_EC2_PRIVATE_IP>
NODE_IP=$EC2_IP
EOF

echo ".env template successfully created in the current directory."
echo "---------------------------------------------------------"
echo "Docker installation complete!"
echo "IMPORTANT: To apply the group changes without logging out,"
echo "please run the following command manually:"
echo ""
echo "    newgrp docker"
echo "---------------------------------------------------------"
