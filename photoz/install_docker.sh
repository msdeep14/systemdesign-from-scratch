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
echo "Docker installation complete!"
echo "IMPORTANT: To apply the group changes without logging out,"
echo "please run the following command manually:"
echo ""
echo "    newgrp docker"
echo "---------------------------------------------------------"
