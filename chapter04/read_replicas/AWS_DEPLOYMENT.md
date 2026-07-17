# Migrating a Live Database to Read Replicas on AWS

For a live, production architecture running on AWS EC2, migrating from a Single-Node database to a Primary-Replica architecture requires a brief maintenance window. The deployment requires updating PostgreSQL's `wal_level` parameter which requires a server restart.

## 1. Architecture Changes Required

All Terraform changes (Replica EC2 instances and Security Groups) have been implemented in the `iaac/aws/terraform` directory. To modify the number of replicas, simply update `db_replica_count = 1` in `terraform.tfvars`.

---

## 2. Deploying to AWS

Depending on your current state, there are two ways to deploy this architecture.

### Scenario A: Clean Deployment (Starting from Scratch)
If you are provisioning a brand new AWS environment, the entire primary-replica architecture is 100% automated via Terraform. 

1. Ensure `db_replica_count = 1` in your `terraform.tfvars`.
2. Run Terraform:
```bash
cd iaac/aws/terraform
terraform apply -auto-approve
```
**That's it!** The Terraform `user_data` script will automatically boot the Primary Database, configure streaming replication (`wal_level=replica`), create the users, and then automatically clone the data to the Replica instance on boot.

---

### Scenario B: Live Migration (Adding Replicas to an Existing Environment)
If your application is already running in production with a single Database node, you must perform a brief maintenance window to manually configure the Primary database for replication before Terraform provisions the new replicas.

To ensure zero data loss, follow this strict sequence:

**Step 1: Commit and Push Changes**
Because Terraform's EC2 startup script clones your repository directly from GitHub to configure the new replicas, you MUST commit and push all Read Replica code changes to your `main` branch *before* proceeding.
```bash
git add .
git commit -m "add read replicas"
git push origin main
```

**Step 2: Stop Traffic (Maintenance Window Begins)**
SSH into the App Servers and stop the web service to ensure no new writes occur while the primary is restarting.
```bash
# On App EC2 Instances:
cd systemdesign-from-scratch/photoz/
docker compose -f docker-compose-app.yml stop web
```

**Step 3: Prepare the Primary DB**
Configure the Primary database to support streaming replication.
1. SSH into the Primary DB EC2 instance.
2. Pull the latest code and execute the replication script:
```bash
# On Primary DB EC2 Instance:
cd systemdesign-from-scratch/photoz/
git pull origin main
docker exec -i photoz-db-1 bash < ./postgres-init/02-setup-replication.sh
```
3. **Restart** the PostgreSQL container on the Primary instance. This is strictly required for the `wal_level` change to take effect:
```bash
# On Primary DB EC2 Instance:
docker compose -f docker-compose-db.yml restart db
```

**Step 4: Apply Terraform & Bootstrap Replicas**
Run Terraform to provision the new Security Group rules and the new Replica EC2 instance. 
Because the Primary DB is already prepared, the Replica EC2's startup script will automatically clone the repository, run `pg_basebackup`, and start streaming immediately.
```bash
cd iaac/aws/terraform
terraform plan
terraform apply -auto-approve
```
*(Take note of the `database_replica_private_ips` in the output, you will need it for Step 5).*

**Step 5: Update and Restart App Servers**
1. SSH into the App Server EC2 instances.
2. Update the `.env` file to point to the new replica's private IP (which was outputted in Step 4):
```bash
# On App EC2 Instances:
cd systemdesign-from-scratch/photoz/
sudo bash -c 'echo "REPLICA_DB_HOST=<REPLICA_IP_FROM_TERRAFORM_OUTPUT>" >> .env'
sudo bash -c 'echo "REPLICA_DB_PORT=6432" >> .env'
```
3. Pull the latest code and restart the Gunicorn/Django containers:
```bash
# On App EC2 Instances:
git pull origin main
docker compose -f docker-compose-app.yml up -d --build
```

**Step 6: Restore Traffic**
Monitor the Replica EC2 instance metrics and the App Server logs to ensure read traffic is flowing successfully. (Maintenance Window Ends).

---

## 3. Adding More Replicas in the Future (Zero Downtime)

> **NOTE:** This needs to be explored more on how it should be done. The below recommendations are not tested yet and just kept for reference.

Once the architecture is established, scaling horizontally by adding *more* replicas **should be** completely seamless.

1. **Update Terraform**: Increase the `db_replica_count` variable in `terraform.tfvars`.
2. **Apply**: Run `terraform apply`. AWS automatically provisions new EC2 instances.
3. **Auto-Bootstrap**: The new Replicas automatically connect to the Primary and run `pg_basebackup`. Because `pg_basebackup` is non-blocking, it does not impact the Primary's performance or require any restarts.
4. **Register Replicas**: If you are using a pool of multiple replicas, you will typically place an internal Load Balancer (e.g., HAProxy or AWS NLB) in front of them, or register them with Consul for service discovery.
5. **Done**: The App servers instantly begin routing a portion of their read queries to the newly provisioned replicas.
