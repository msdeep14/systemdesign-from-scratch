# Migrating a Live Database to Read Replicas on AWS

For a live, production architecture running on AWS EC2, migrating from a Single-Node database to a Primary-Replica architecture requires a brief maintenance window. The deployment requires updating PostgreSQL's `wal_level` parameter which requires a server restart.

## 1. Architecture Changes Required

All Terraform changes (Replica EC2 instances and Security Groups) have been implemented in the `iaac/aws/terraform` directory. To modify the number of replicas, simply update `db_replica_count = 1` in `terraform.tfvars`.

---

## 2. Live Migration Steps (The Runbook)

To ensure zero data loss and avoid unexpected scenarios, follow step-wise sequence:

**Step 1: Apply Terraform Changes**
Run Terraform to provision the new Security Group rules and the new Replica EC2 instance. 
```bash
cd iaac/aws/terraform
terraform plan
terraform apply -auto-approve
```
*(Take note of the `database_replica_private_ips` in the output, you will need it for Step 5).*

**Step 2: Stop Traffic (Maintenance Window Begins)**
SSH into the Load Balancer (Nginx) EC2 instance and stop the nginx container, or SSH into the App Servers and stop the web service to ensure no new writes occur while the primary is restarting.
```bash
# On App EC2 Instances:
cd ~/photoz
docker compose -f docker-compose-app.yml stop web
```

**Step 3: Prepare the Primary**
1. SSH into the Primary DB EC2 instance.
2. Run the `setup-replication.sh` script to set `wal_level = replica` and create the `replicator` user:
```bash
# On Primary DB EC2 Instance:
docker exec -i photoz-db-1 bash < ./postgres-init/02-setup-replication.sh
```
3. **Restart** the PostgreSQL container on the Primary instance. This is strictly required for the `wal_level` change to take effect:
```bash
# On Primary DB EC2 Instance:
docker compose -f docker-compose-db.yml restart db
```

**Step 4: Bootstrap the Replica**
You don't need to do anything! The `aws_instance.db_replica` startup script automatically clones the repo and runs `docker compose -f docker-compose-replica.yml up -d`. The entrypoint script will automatically wait for the primary, run `pg_basebackup` to copy the data, and start PostgreSQL in standby mode.

**Step 5: Update and Restart App Servers**
1. SSH into the App Server EC2 instances.
2. Update the `.env` file to point to the new replica's private IP (which was outputted in Step 1):
```bash
# On App EC2 Instances:
echo "REPLICA_DB_HOST=<REPLICA_IP_FROM_TERRAFORM_OUTPUT>" >> .env
echo "REPLICA_DB_PORT=6432" >> .env
```
3. Pull the latest code and restart the Gunicorn/Django containers:
```bash
# On App EC2 Instances:
git pull origin main
docker compose -f docker-compose-app.yml up -d --build
```

**Step 6: Restore Traffic**
If you stopped the Nginx container on the Load Balancer, start it back up. Monitor the Replica EC2 instance metrics to ensure read traffic is flowing successfully. (Maintenance Window Ends).

---

## 3. Adding More Replicas in the Future (Zero Downtime)

> **NOTE:** This needs to be explored more on how it should be done. The below recommendations are not tested yet and just kept for reference.

Once the architecture is established, scaling horizontally by adding *more* replicas **should be** completely seamless.

1. **Update Terraform**: Increase the `db_replica_count` variable in `terraform.tfvars`.
2. **Apply**: Run `terraform apply`. AWS automatically provisions new EC2 instances.
3. **Auto-Bootstrap**: The new Replicas automatically connect to the Primary and run `pg_basebackup`. Because `pg_basebackup` is non-blocking, it does not impact the Primary's performance or require any restarts.
4. **Register Replicas**: If you are using a pool of multiple replicas, you will typically place an internal Load Balancer (e.g., HAProxy or AWS NLB) in front of them, or register them with Consul for service discovery.
5. **Done**: The App servers instantly begin routing a portion of their read queries to the newly provisioned replicas.
