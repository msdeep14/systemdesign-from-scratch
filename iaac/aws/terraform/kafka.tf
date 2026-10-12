locals {
  kafka_key_name          = var.kafka_key_name != "" ? var.kafka_key_name : var.app_key_name
  kafka_cluster_id        = "4L622nShTUiBenVznCXfrA"
  kafka_controller_ips    = [for i in range(3) : "10.0.${i}.20"]
  kafka_broker_ips        = [for i in range(3) : "10.0.${i}.30"]
  kafka_quorum_voters     = join(",", [for i in range(3) : "${i + 1}@${local.kafka_controller_ips[i]}:9093"])
  kafka_bootstrap_servers = join(",", [for ip in local.kafka_broker_ips : "${ip}:9092"])
}

# -------------------------------------------------------------------------
# Control Plane: 3 Dedicated KRaft Controllers (Consensus Quorum)
# -------------------------------------------------------------------------
resource "aws_instance" "kafka_controller" {
  count                  = var.create_kafka_cluster ? 3 : 0
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.kafka_controller_instance_type
  subnet_id              = local.subnet_ids[count.index]
  private_ip             = local.kafka_controller_ips[count.index]
  key_name               = local.kafka_key_name
  vpc_security_group_ids = [local.kafka_controller_sg_id]
  iam_instance_profile   = local.iam_instance_profile

  user_data_replace_on_change = true

  user_data = <<-EOF
#!/bin/bash
set -e
sudo apt-get update
sudo apt-get install -y ca-certificates curl

# Install Docker
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io

mkdir -p /var/lib/kafka/data/kafka
chmod -R 777 /var/lib/kafka/data

# Run Kafka in KRaft Controller Mode
docker run -d --name kafka-controller \
  --restart always \
  --net=host \
  -e KAFKA_NODE_ID=${count.index + 1} \
  -e KAFKA_PROCESS_ROLES=controller \
  -e KAFKA_LISTENERS=CONTROLLER://0.0.0.0:9093 \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS=${local.kafka_quorum_voters} \
  -e CLUSTER_ID=${local.kafka_cluster_id} \
  -e KAFKA_CLUSTER_ID=${local.kafka_cluster_id} \
  -e KAFKA_LOG_DIRS=/var/lib/kafka/data/kafka \
  -v /var/lib/kafka/data:/var/lib/kafka/data \
  apache/kafka:4.3.1
EOF

  tags = {
    Name = "photoz-kafka-controller-${count.index + 1}${local.env_suffix}"
    Role = "kafka-controller"
  }
}

# -------------------------------------------------------------------------
# Data Plane: 3 Dedicated Kafka Brokers + gp3 EBS Volumes
# -------------------------------------------------------------------------
resource "aws_ebs_volume" "kafka_broker_data" {
  count             = var.create_kafka_cluster ? 3 : 0
  availability_zone = data.aws_availability_zones.available.names[count.index]
  size              = var.kafka_ebs_volume_size
  type              = "gp3"

  tags = {
    Name = "photoz-kafka-broker-data-${count.index + 1}${local.env_suffix}"
  }
}

resource "aws_instance" "kafka_broker" {
  count                  = var.create_kafka_cluster ? 3 : 0
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.kafka_broker_instance_type
  subnet_id              = local.subnet_ids[count.index]
  private_ip             = local.kafka_broker_ips[count.index]
  key_name               = local.kafka_key_name
  vpc_security_group_ids = [local.kafka_broker_sg_id]
  iam_instance_profile   = local.iam_instance_profile

  user_data_replace_on_change = true

  user_data = <<-EOF
#!/bin/bash
set -e
sudo apt-get update
sudo apt-get install -y ca-certificates curl

# Wait for EBS volume attachment
DEVICE="/dev/xvdf"
for i in {1..30}; do
  if [ -b "$DEVICE" ]; then break; fi
  NVME_DEV=$(ls /dev/nvme*n1 2>/dev/null | grep -v nvme0n1 | head -n 1 || true)
  if [ -n "$NVME_DEV" ] && [ -b "$NVME_DEV" ]; then
    DEVICE="$NVME_DEV"
    break
  fi
  echo "Waiting for data volume to attach..."
  sleep 3
done

mkdir -p /var/lib/kafka/data
if [ -b "$DEVICE" ]; then
  if ! blkid "$DEVICE"; then
    mkfs -t ext4 "$DEVICE"
  fi
  mount "$DEVICE" /var/lib/kafka/data
  echo "$DEVICE /var/lib/kafka/data ext4 defaults,nofail 0 2" >> /etc/fstab
fi
rm -rf /var/lib/kafka/data/lost+found
mkdir -p /var/lib/kafka/data/kafka
chmod -R 777 /var/lib/kafka/data

# Install Docker
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io

# Run Kafka in Broker Mode
docker run -d --name kafka-broker \
  --restart always \
  --net=host \
  -e KAFKA_NODE_ID=${101 + count.index} \
  -e KAFKA_PROCESS_ROLES=broker \
  -e KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:9092 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://${local.kafka_broker_ips[count.index]}:9092 \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS=${local.kafka_quorum_voters} \
  -e CLUSTER_ID=${local.kafka_cluster_id} \
  -e KAFKA_CLUSTER_ID=${local.kafka_cluster_id} \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=3 \
  -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=3 \
  -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=2 \
  -e KAFKA_DEFAULT_REPLICATION_FACTOR=3 \
  -e KAFKA_LOG_DIRS=/var/lib/kafka/data/kafka \
  -v /var/lib/kafka/data:/var/lib/kafka/data \
  apache/kafka:4.3.1
EOF

  tags = {
    Name = "photoz-kafka-broker-${count.index + 1}${local.env_suffix}"
    Role = "kafka-broker"
  }
}

resource "aws_volume_attachment" "kafka_broker_data" {
  count       = var.create_kafka_cluster ? 3 : 0
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.kafka_broker_data[count.index].id
  instance_id = aws_instance.kafka_broker[count.index].id
}
