# Execution Log - v0

## Phase: Setup Slow Upload Scenario (Commit: dc7442f)
*   **Analysis:** Based on the scenario of showcasing Gunicorn's synchronous workers getting blocked by slow client uploads, we set up `simulate_slow_upload.py` and `test_responsiveness.py` to replicate the problem.
*   **Actions:**
    *   Cleaned up old documentation files from `skills/` directory (kept `SKILLS.md`).
    *   Updated `SKILLS.md` to reference `chapter01` for the initial architecture.
    *   Created `simulate_slow_upload.py` to send photo data extremely slowly.
    *   Created `test_responsiveness.py` to test basic API responsiveness.
*   **Notes/Edge Cases:** None encountered yet.

## Phase: Execute Slow Upload Scenario (Commit: 3434833)
*   **Analysis:** Analyzed the test results from the 3 slow upload clients running against the 3 Gunicorn workers. The test successfully proved the vulnerability of synchronous workers, showing a complete paralysis of the API (`Read timed out`).
*   **Actions:**
    *   Updated `simulate_slow_upload.py` and `test_responsiveness.py` to authenticate fully and mimic a real browser session.
    *   Added photo-upload population to the fast responsiveness test so the newsfeed had real data to query.
    *   Created `TESTING.md` in `chapter03/slow_application_server/` to document the testing setup, execution steps, and exact HTTP logs.
    *   Recorded the final test results in the markdown file showing the 3 workers being completely blocked.
*   **Notes/Edge Cases:** The slow connections were forcefully terminated around the 33-second mark (`[Errno 32] Broken pipe`). This is exactly expected and caused by Gunicorn's default 30-second worker timeout, which forces Gunicorn to kill and restart frozen workers.

## Phase: Nginx Implementation (Commit: 01a6a47)
*   **Analysis:** We removed direct public access to Gunicorn by taking away its port `80:8000` mapping, as Gunicorn is not designed to buffer network requests or protect against slow clients. We introduced an Nginx reverse proxy explicitly configured to buffer the request body (`client_body_buffer_size 20M;`) before forwarding the traffic to Gunicorn.
*   **Actions:**
    *   Removed `whitenoise` from `requirements.txt` and `settings.py` since Nginx now serves static files.
    *   Created `photoz/nginx/Dockerfile` and `photoz/nginx/nginx.conf`.
    *   Updated `docker-compose.yml` to include the new `nginx` service mapped to port `80`, routing traffic to the internal `web:8000` upstream.
    *   Rebuilt and restarted the Docker Compose cluster.
*   **Notes/Edge Cases:** 
    *   Nginx successfully isolates Gunicorn from network latency.
    *   **EC2 Docker Bug:** During testing on Ubuntu EC2, running `docker-compose down` occasionally threw a `permission denied` error preventing containers from stopping. This is a known AppArmor bug with snap-installed Docker. Resolved by restarting the daemon: `sudo systemctl restart snap.docker.dockerd`.

## Phase: Server Overload Simulation Setup (Commit: a111032)
*   **Analysis:** We needed to replicate a scenario where a severely under-provisioned EC2 instance (represented by our Docker container) gets its CPU and RAM exhausted by concurrent requests, causing unresponsiveness.
*   **Actions:**
    *   Created `chapter03/server_overload/` directory to store load testing scripts.
    *   Added Docker deploy resource limits to `web` service in `docker-compose.yml` (`cpus: 0.3`, `memory: 250M`) to simulate a small machine.
    *   Created `simulate_high_load.py` to bombard the signup endpoint with hundreds of concurrent requests, starving the container of CPU and memory.
    *   Created `monitor_health.py` to repeatedly test the responsiveness of the web app.
*   **Notes/Edge Cases:** This sets up the environment to demonstrate vertical and horizontal scaling.

## Phase: Vertical Scaling (Simulation) (Commit: a111032)
*   **Analysis:** We confirmed that the `0.3` CPU limit caused Gunicorn workers to hit 100% CPU utilization, creating a massive backlog of "zombie" requests and causing 502/timeout errors. To resolve this without architectural changes, we simulated a hardware upgrade (Vertical Scaling).
*   **Actions:**
    *   Updated `docker-compose.yml` to increase the `web` service limits from `cpus: 0.3` to `cpus: 2.0` and `memory: 250M` to `memory: 1G`.
*   **Notes/Edge Cases:** Vertical scaling is the simplest fix for an overloaded server because it requires zero code changes. However, it has physical limits (a machine can only be so large) and is prone to single points of failure.

## Phase: Horizontal Scaling - Stage 1 (Docker Replicas) (Commit: 14da934)
*   **Analysis:** Vertical scaling successfully handled 7 concurrent signups but failed miserably when simulating massive viral traffic (e.g., 50+ concurrent signups), proving that a single vertically scaled machine still has strict compute limits. To handle massive traffic, we need to scale horizontally.
*   **Actions:**
    *   Updated `docker-compose.yml` to add `replicas: 3` to the `web` service's `deploy` block.
    *   Nginx automatically load balances traffic across all 3 running container replicas using Docker's internal DNS.
*   **Notes/Edge Cases:** This effectively gives our architecture 6.0 CPUs and 15 workers distributed across 3 containers on the *same* physical host. However, if traffic scales beyond the physical limits of the single EC2 host itself, we must move to Stage 2: adding multiple EC2 instances.

## Phase: Horizontal Scaling - Stage 2 (Decoupled Database & 3-Tier Architecture) (Commit: a091946)
*   **Analysis:** To truly scale horizontally and avoid physical host lockups, the architecture must be split into isolated tiers. We decoupled the Database to its own EC2 instance, the App layer to its own EC2 instances, and the Load Balancer to its own EC2 instance.
*   **Actions:**
    *   Shattered the monolithic `docker-compose.yml` into three role-specific files: `docker-compose-db.yml`, `docker-compose-app.yml`, and `docker-compose-lb.yml`.
    *   Updated `photoz/.env` with a `POSTGRES_HOST` placeholder so the App instances can dynamically point to the remote DB instance.
    *   Updated `photoz/nginx/nginx.conf` with `upstream` placeholders so the Load Balancer can route traffic across multiple App Instance IPs.
    *   Since static and media files were already decoupled via S3 (`USE_S3=True`), the Load Balancer (Nginx) no longer needed a local volume mount for `/static/`, making the decoupling process seamless.
*   **Notes/Edge Cases:** This completes the transition to a production-grade 3-tier architecture. The App tier can now be scaled horizontally infinitely just by spinning up more EC2 instances and adding their IPs to the Nginx upstream.

## Phase: Distributed Logging (AWS CloudWatch) (Commit: 2d17c28)
*   **Analysis:** Transitioning to a horizontally scaled architecture introduces a massive observability issue: logs are scattered across multiple isolated EC2 instances. To debug effectively, we must centralize them.
*   **Actions:**
    *   Updated `docker-compose-app.yml` and `docker-compose-lb.yml` to utilize Docker's native `awslogs` driver.
    *   Configured the driver to stream logs to `photoz-app-logs` and `photoz-lb-logs` CloudWatch groups in the `ap-south-1` region.
    *   Configured the log stream name to map to `{{.Hostname}}` so logs can be traced back to the specific App Server EC2 instance.
    *   Updated `aws-deployment-guide.md` to instruct the user to attach an IAM Role with `CloudWatchLogsFullAccess` to their EC2 instances before deploying.
*   **Notes/Edge Cases:** This enables a single, searchable pane of glass for all distributed server logs, effectively mimicking enterprise observability without the overhead of maintaining a selfhosted ELK stack.

## Phase: Static File Serving (Decoupled Nginx) (Commit: 65b130d)
*   **Analysis:** In the monolithic architecture, Nginx served static files from a shared Docker volume. In the decoupled architecture, Nginx and Django are on different EC2 instances, breaking the volume mount and causing Django to throw 404s for static files.
*   **Actions:**
    *   Leveraged the fact that the entire repository is cloned onto the Load Balancer EC2 instance.
    *   Updated `photoz/docker-compose-lb.yml` to mount the local `./static` directory into the Nginx container as a read-only volume.
    *   Restored the `location /static/` block in `photoz/nginx/nginx.conf` with an `alias` directive to serve the CSS/JS directly from the local disk.
    *   Updated `photoz/nginx/Dockerfile` to copy the custom `502.html` Bad Gateway error page.
*   **Notes/Edge Cases:** This fixes the UI without requiring an external CDN for basic static files, while still bypassing Django for static asset requests.

## Phase: Distributed Logging Optimization & Node Observability (Analysis) (Commit: 70c9885)
*   **Analysis:** During load testing, two observability issues were discovered with the initial CloudWatch configuration. First, `docker-compose`'s handling of the `awslogs-stream` template caused the stream to literally be named `app-node-{{.ID}}` instead of evaluating the template. Switching to `awslogs-stream-prefix` fixed the template issue but still failed to solve the core problem: the Django log payloads themselves do not contain the EC2 hostname/IP, making it impossible to trace an aggregated log line back to the specific physical node that generated it.
*   **Actions:**
    *   Inject an explicit `NODE_IP` environment variable via `.env` on each EC2 instance.
    *   Update `docker-compose-app.yml` to use `awslogs-stream: "app-node-${NODE_IP}"` for perfectly readable stream names without relying on Docker's template parser (tried couple of combinations but didn't work as expected).
    *   Update Django's `LOGGING` formatter to automatically prefix every log payload with `[app-node-${NODE_IP}]`.
*   **Notes/Edge Cases:** NA

## Phase: Terraform IaC Automation (Commit: 240d6f2)
*   **Analysis:** The manual deployment steps described in `aws-deployment-guide.md` were too labor-intensive. We required a modular, infrastructure-as-code solution to automate VPC/Subnet provisioning, strict decoupled security group rules (DB <- App <- LB <- World), and automated application bootstrapping.
*   **Actions:**
    *   Created `chapter03/iaac/terraform/` directory containing modular Terraform scripts.
    *   Added conditional resource creation toggles (`create_vpc`, `create_iam_role`) to support reusing existing infrastructure.
    *   Implemented `http` data source to dynamically fetch the deploying user's public IP (`ipv4.icanhazip.com/32`) and restrict Port 22 (SSH) strictly to that IP.
    *   Orchestrated complete EC2 bootstrapping via `user_data`: passing the dynamically generated DB private IP into the App nodes' `.env` files, and passing the App node IPs into the LB's `nginx.conf` upstream block.
    *   Created `destroy.sh` wrapper script using `terraform state rm` to allow targeted tearing down of compute resources without destroying the VPC or IAM foundations.
    *   Added `*.tfvars` to a local `.gitignore` to prevent secret leakage.
*   **Notes/Edge Cases:** The use of `user_data` completely eliminated the need for manual SSH configuration. The dynamic IP fetching required an external HTTP provider but resulted in a significantly more secure default SSH posture.

## Phase: Terraform IaC - Database Persistence & Automated Backups (Commit: 240d6f2)
*   **Analysis:** Ability to skip destroying the database instance during infrastructure teardown, re-use the preserved database instance in future launches, and back up the database data.
*   **Decisions:** 
    *   Introduce `--skip-db` to `destroy.sh` which executes `terraform state rm 'aws_instance.db_node[0]'` to leave the DB running and untracked.
    *   Introduce `create_db_node` and `existing_db_private_ip` variables to `variables.tf`.
    *   Conditionally provision the DB node in `main.tf` and dynamically feed `existing_db_private_ip` to the App nodes if `create_db_node` is `false`.
    *   Inject a daily `cron` script into the DB node's `user_data` that runs `pg_dump` and uploads the snapshot to the existing S3 bucket using the IAM profile.
    *   Attach `AmazonS3FullAccess` to the EC2 IAM Role to allow the DB node to execute `aws s3 cp`.

## Phase: Aggressive Image Optimization & Cost Reduction (Commit: c7e3529cdafaf4959575e21dda72304528c0de62)
*   **Analysis:** Identified hidden cost in S3 Data Transfer OUT. The application was compressing images via Pillow (`quality=85`) but not downscaling the physical resolution, resulting in ~600KB images. Under heavy load (e.g., 240,000 photo downloads/hour), this would result in ~105 TB of monthly data transfer (~$8,150/month).
*   **Actions:**
    *   Updated `photoz/photos/utils.py` `compress_photo` function.
    *   Added logic to cap image width at `1080px` using `Image.LANCZOS` resampling.
    *   Reduced Pillow save quality from `85` to `70`.
*   **Notes/Edge Cases:** Code fix reduces the average image payload to roughly ~150KB. This drops the estimated S3 data transfer to ~26 TB/month, instantly saving approximately $5,800/month in AWS egress fees. CDN exploration in future.

## Phase: Client-Side Image Compression & Auto-Scaling Pivot (Commit: 59e7d96969d2e4145bd933add858bc0fe04be681)
*   **Analysis:** We evaluated the impact of compressing images *before* they are uploaded. Sending a 150KB image over the network instead of a 1.5MB image drastically improves user experience on mobile networks. Crucially, it drops the "Processed Bytes" penalty on an AWS Application Load Balancer (ALB) to almost zero. The math proves that with client-side compression, a fully managed AWS ALB actually becomes *cheaper* ($29/mo) than maintaining a custom open-source Nginx Load Balancer ($30/mo).
*   **Actions:**
    *   Updated `photoz/photos/templates/photos/upload.html`.
    *   Injected the `browser-image-compression` library via CDN.
    *   Added an async JavaScript listener to intercept the `<form>` submission.
    *   Configured the web-worker to downscale the image to max `1080px` and compress to `0.7` quality directly in the user's browser.
    *   Dynamically replaced the heavy file in the input with the lightweight compressed Blob before sending the HTTP POST.
*   **Notes/Edge Cases:** The backend `utils.py` Pillow logic is intentionally left intact as a secondary defense to ensure that API requests skipping the browser JS are still forcefully compressed and resized before hitting S3.

## Phase: Infrastructure & Frontend Debugging (Commit: 97a352fd7a47533e3c28b9ee6ad5091d5e900173)
*   **Analysis:** After deploying the horizontally scaled architecture, we encountered three distinct issues: CloudWatch log groups persisting after `terraform destroy`, a database `IntegrityError` during boot, and a silent failure of the client-side compression script.
*   **Actions:**
    *   **CloudWatch Logs Retention:** Docker automatically created the `awslogs` groups on EC2 boot, preventing Terraform from tracking or destroying them. Created `cloudwatch.tf` to explicitly manage `photoz-app-logs` and `photoz-lb-logs` with a 7-day retention policy so they are cleanly deleted on `terraform destroy`.
    *   **Database Migration Race Condition:** Booting multiple App EC2 instances simultaneously caused a distributed race condition where both nodes hit the empty Postgres database and tried to run `python manage.py migrate` at the exact same millisecond. This caused an `IntegrityError` (violating unique constraint on `auth_permission`) and crashed the container. Fixed by adding `restart: always` to `docker-compose-app.yml` so the container revives and successfully skips the migration after the other node finishes.
    *   **WebWorker CORS Exception:** Accessing the Load Balancer via HTTP triggered a Cross-Origin-Opener-Policy browser block on the client-side image compression WebWorker. Disabled WebWorkers (`useWebWorker: false`) to bypass local/HTTP restrictions.
    *   **Verbose JS Error Logging:** Updated the `try/catch` block in `upload.html` to inject `error.message` into the hidden `client_compressed` payload, allowing the backend Django logs to instantly reveal exactly why frontend JS failed.
    *   **JS Form Selector Bug:** Discovered that `document.querySelector('form')` in `upload.html` was incorrectly grabbing the Search Form in the navbar (the first form in the DOM). This caused the WebWorker event listener to attach to the search bar instead of the photo upload form, completely bypassing client-side compression. Fixed by using `fileInput.closest('form')` to precisely target the correct form. This needs HTTPS for client compression to work, else it's blocked on the modern browsers with error `browserImageCompression is not defined`.
    *   **Same-Origin Script Bypass:** To bypass the strict Chrome security policies blocking the third-party CDN script on HTTP, we downloaded `browser-image-compression.js` directly into `photoz/static/js/`. Serving it locally as a same-origin request bypasses the Cross-Origin-Opener-Policy blocks without requiring HTTPS.
*   **Notes/Edge Cases:** The CloudWatch fix required users to manually run `aws logs delete-log-group` if the logs were already created by Docker before Terraform attempted to adopt them.
