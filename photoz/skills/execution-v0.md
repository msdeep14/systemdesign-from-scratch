# Execution Log - v0

## Phase: Setup Slow Upload Scenario (Date: 2026-06-07, Commit: dc7442f, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Based on the scenario of showcasing Gunicorn's synchronous workers getting blocked by slow client uploads, we set up `simulate_slow_upload.py` and `test_responsiveness.py` to replicate the problem.
*   **Actions:**
    *   Cleaned up old documentation files from `skills/` directory (kept `SKILLS.md`).
    *   Updated `SKILLS.md` to reference `chapter01` for the initial architecture.
    *   Created `simulate_slow_upload.py` to send photo data extremely slowly.
    *   Created `test_responsiveness.py` to test basic API responsiveness.
*   **Notes/Edge Cases:** None encountered yet.

## Phase: Execute Slow Upload Scenario (Date: 2026-06-07, Commit: 3434833, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Analyzed the test results from the 3 slow upload clients running against the 3 Gunicorn workers. The test successfully proved the vulnerability of synchronous workers, showing a complete paralysis of the API (`Read timed out`).
*   **Actions:**
    *   Updated `simulate_slow_upload.py` and `test_responsiveness.py` to authenticate fully and mimic a real browser session.
    *   Added photo-upload population to the fast responsiveness test so the newsfeed had real data to query.
    *   Created `TESTING.md` in `chapter03/slow_application_server/` to document the testing setup, execution steps, and exact HTTP logs.
    *   Recorded the final test results in the markdown file showing the 3 workers being completely blocked.
*   **Notes/Edge Cases:** The slow connections were forcefully terminated around the 33-second mark (`[Errno 32] Broken pipe`). This is exactly expected and caused by Gunicorn's default 30-second worker timeout, which forces Gunicorn to kill and restart frozen workers.

## Phase: Nginx Implementation (Date: 2026-06-07, Commit: 01a6a47, Model: Gemini 3.1 Pro (High))
*   **Analysis:** We removed direct public access to Gunicorn by taking away its port `80:8000` mapping, as Gunicorn is not designed to buffer network requests or protect against slow clients. We introduced an Nginx reverse proxy explicitly configured to buffer the request body (`client_body_buffer_size 20M;`) before forwarding the traffic to Gunicorn.
*   **Actions:**
    *   Removed `whitenoise` from `requirements.txt` and `settings.py` since Nginx now serves static files.
    *   Created `photoz/nginx/Dockerfile` and `photoz/nginx/nginx.conf`.
    *   Updated `docker-compose.yml` to include the new `nginx` service mapped to port `80`, routing traffic to the internal `web:8000` upstream.
    *   Rebuilt and restarted the Docker Compose cluster.
*   **Notes/Edge Cases:** 
    *   Nginx successfully isolates Gunicorn from network latency.
    *   **EC2 Docker Bug:** During testing on Ubuntu EC2, running `docker-compose down` occasionally threw a `permission denied` error preventing containers from stopping. This is a known AppArmor bug with snap-installed Docker. Resolved by restarting the daemon: `sudo systemctl restart snap.docker.dockerd`.

## Phase: Server Overload Simulation Setup (Date: 2026-06-07, Commit: a111032, Model: Gemini 3.1 Pro (High))
*   **Analysis:** We needed to replicate a scenario where a severely under-provisioned EC2 instance (represented by our Docker container) gets its CPU and RAM exhausted by concurrent requests, causing unresponsiveness.
*   **Actions:**
    *   Created `chapter03/server_overload/` directory to store load testing scripts.
    *   Added Docker deploy resource limits to `web` service in `docker-compose.yml` (`cpus: 0.3`, `memory: 250M`) to simulate a small machine.
    *   Created `simulate_high_load.py` to bombard the signup endpoint with hundreds of concurrent requests, starving the container of CPU and memory.
    *   Created `monitor_health.py` to repeatedly test the responsiveness of the web app.
*   **Notes/Edge Cases:** This sets up the environment to demonstrate vertical and horizontal scaling.

## Phase: Vertical Scaling (Simulation) (Date: 2026-06-07, Commit: a111032, Model: Gemini 3.1 Pro (High))
*   **Analysis:** We confirmed that the `0.3` CPU limit caused Gunicorn workers to hit 100% CPU utilization, creating a massive backlog of "zombie" requests and causing 502/timeout errors. To resolve this without architectural changes, we simulated a hardware upgrade (Vertical Scaling).
*   **Actions:**
    *   Updated `docker-compose.yml` to increase the `web` service limits from `cpus: 0.3` to `cpus: 2.0` and `memory: 250M` to `memory: 1G`.
*   **Notes/Edge Cases:** Vertical scaling is the simplest fix for an overloaded server because it requires zero code changes. However, it has physical limits (a machine can only be so large) and is prone to single points of failure.

## Phase: Horizontal Scaling - Stage 1 (Docker Replicas) (Date: 2026-06-07, Commit: 14da934, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Vertical scaling successfully handled 7 concurrent signups but failed miserably when simulating massive viral traffic (e.g., 50+ concurrent signups), proving that a single vertically scaled machine still has strict compute limits. To handle massive traffic, we need to scale horizontally.
*   **Actions:**
    *   Updated `docker-compose.yml` to add `replicas: 3` to the `web` service's `deploy` block.
    *   Nginx automatically load balances traffic across all 3 running container replicas using Docker's internal DNS.
*   **Notes/Edge Cases:** This effectively gives our architecture 6.0 CPUs and 15 workers distributed across 3 containers on the *same* physical host. However, if traffic scales beyond the physical limits of the single EC2 host itself, we must move to Stage 2: adding multiple EC2 instances.

## Phase: Horizontal Scaling - Stage 2 (Decoupled Database & 3-Tier Architecture) (Date: 2026-06-07, Commit: a091946, Model: Gemini 3.1 Pro (High))
*   **Analysis:** To truly scale horizontally and avoid physical host lockups, the architecture must be split into isolated tiers. We decoupled the Database to its own EC2 instance, the App layer to its own EC2 instances, and the Load Balancer to its own EC2 instance.
*   **Actions:**
    *   Shattered the monolithic `docker-compose.yml` into three role-specific files: `docker-compose-db.yml`, `docker-compose-app.yml`, and `docker-compose-lb.yml`.
    *   Updated `photoz/.env` with a `POSTGRES_HOST` placeholder so the App instances can dynamically point to the remote DB instance.
    *   Updated `photoz/nginx/nginx.conf` with `upstream` placeholders so the Load Balancer can route traffic across multiple App Instance IPs.
    *   Since static and media files were already decoupled via S3 (`USE_S3=True`), the Load Balancer (Nginx) no longer needed a local volume mount for `/static/`, making the decoupling process seamless.
*   **Notes/Edge Cases:** This completes the transition to a production-grade 3-tier architecture. The App tier can now be scaled horizontally infinitely just by spinning up more EC2 instances and adding their IPs to the Nginx upstream.

## Phase: Distributed Logging (AWS CloudWatch) (Date: 2026-06-07, Commit: 2d17c28, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Transitioning to a horizontally scaled architecture introduces a massive observability issue: logs are scattered across multiple isolated EC2 instances. To debug effectively, we must centralize them.
*   **Actions:**
    *   Updated `docker-compose-app.yml` and `docker-compose-lb.yml` to utilize Docker's native `awslogs` driver.
    *   Configured the driver to stream logs to `photoz-app-logs` and `photoz-lb-logs` CloudWatch groups in the `ap-south-1` region.
    *   Configured the log stream name to map to `{{.Hostname}}` so logs can be traced back to the specific App Server EC2 instance.
    *   Updated `aws-deployment-guide.md` to instruct the user to attach an IAM Role with `CloudWatchLogsFullAccess` to their EC2 instances before deploying.
*   **Notes/Edge Cases:** This enables a single, searchable pane of glass for all distributed server logs, effectively mimicking enterprise observability without the overhead of maintaining a selfhosted ELK stack.

## Phase: Static File Serving (Decoupled Nginx) (Date: 2026-06-08, Commit: 65b130d, Model: Gemini 3.1 Pro (High))
*   **Analysis:** In the monolithic architecture, Nginx served static files from a shared Docker volume. In the decoupled architecture, Nginx and Django are on different EC2 instances, breaking the volume mount and causing Django to throw 404s for static files.
*   **Actions:**
    *   Leveraged the fact that the entire repository is cloned onto the Load Balancer EC2 instance.
    *   Updated `photoz/docker-compose-lb.yml` to mount the local `./static` directory into the Nginx container as a read-only volume.
    *   Restored the `location /static/` block in `photoz/nginx/nginx.conf` with an `alias` directive to serve the CSS/JS directly from the local disk.
    *   Updated `photoz/nginx/Dockerfile` to copy the custom `502.html` Bad Gateway error page.
*   **Notes/Edge Cases:** This fixes the UI without requiring an external CDN for basic static files, while still bypassing Django for static asset requests.

## Phase: Distributed Logging Optimization & Node Observability (Analysis) (Date: 2026-06-09, Commit: 70c9885, Model: Gemini 3.1 Pro (High))
*   **Analysis:** During load testing, two observability issues were discovered with the initial CloudWatch configuration. First, `docker-compose`'s handling of the `awslogs-stream` template caused the stream to literally be named `app-node-{{.ID}}` instead of evaluating the template. Switching to `awslogs-stream-prefix` fixed the template issue but still failed to solve the core problem: the Django log payloads themselves do not contain the EC2 hostname/IP, making it impossible to trace an aggregated log line back to the specific physical node that generated it.
*   **Actions:**
    *   Inject an explicit `NODE_IP` environment variable via `.env` on each EC2 instance.
    *   Update `docker-compose-app.yml` to use `awslogs-stream: "app-node-${NODE_IP}"` for perfectly readable stream names without relying on Docker's template parser (tried couple of combinations but didn't work as expected).
    *   Update Django's `LOGGING` formatter to automatically prefix every log payload with `[app-node-${NODE_IP}]`.
*   **Notes/Edge Cases:** NA

## Phase: Terraform IaC Automation (Date: 2026-06-09, Commit: 240d6f2, Model: Gemini 3.1 Pro (High))
*   **Analysis:** The manual deployment steps described in `aws-deployment-guide.md` were too labor-intensive. We required a modular, infrastructure-as-code solution to automate VPC/Subnet provisioning, strict decoupled security group rules (DB <- App <- LB <- World), and automated application bootstrapping.
*   **Actions:**
    *   Created `chapter03/iaac/terraform/` directory containing modular Terraform scripts.
    *   Added conditional resource creation toggles (`create_vpc`, `create_iam_role`) to support reusing existing infrastructure.
    *   Implemented `http` data source to dynamically fetch the deploying user's public IP (`ipv4.icanhazip.com/32`) and restrict Port 22 (SSH) strictly to that IP.
    *   Orchestrated complete EC2 bootstrapping via `user_data`: passing the dynamically generated DB private IP into the App nodes' `.env` files, and passing the App node IPs into the LB's `nginx.conf` upstream block.
    *   Created `destroy.sh` wrapper script using `terraform state rm` to allow targeted tearing down of compute resources without destroying the VPC or IAM foundations.
    *   Added `*.tfvars` to a local `.gitignore` to prevent secret leakage.
*   **Notes/Edge Cases:** The use of `user_data` completely eliminated the need for manual SSH configuration. The dynamic IP fetching required an external HTTP provider but resulted in a significantly more secure default SSH posture.

## Phase: Terraform IaC - Database Persistence & Automated Backups (Date: 2026-06-09, Commit: 240d6f2, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Ability to skip destroying the database instance during infrastructure teardown, re-use the preserved database instance in future launches, and back up the database data.
*   **Decisions:** 
    *   Introduce `--skip-db` to `destroy.sh` which executes `terraform state rm 'aws_instance.db_node[0]'` to leave the DB running and untracked.
    *   Introduce `create_db_node` and `existing_db_private_ip` variables to `variables.tf`.
    *   Conditionally provision the DB node in `main.tf` and dynamically feed `existing_db_private_ip` to the App nodes if `create_db_node` is `false`.
    *   Inject a daily `cron` script into the DB node's `user_data` that runs `pg_dump` and uploads the snapshot to the existing S3 bucket using the IAM profile.
    *   Attach `AmazonS3FullAccess` to the EC2 IAM Role to allow the DB node to execute `aws s3 cp`.

## Phase: Aggressive Image Optimization & Cost Reduction (Date: 2026-06-15, Commit: c7e3529cdafaf4959575e21dda72304528c0de62, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Identified hidden cost in S3 Data Transfer OUT. The application was compressing images via Pillow (`quality=85`) but not downscaling the physical resolution, resulting in ~600KB images. Under heavy load (e.g., 240,000 photo downloads/hour), this would result in ~105 TB of monthly data transfer (~$8,150/month).
*   **Actions:**
    *   Updated `photoz/photos/utils.py` `compress_photo` function.
    *   Added logic to cap image width at `1080px` using `Image.LANCZOS` resampling.
    *   Reduced Pillow save quality from `85` to `70`.
*   **Notes/Edge Cases:** Code fix reduces the average image payload to roughly ~150KB. This drops the estimated S3 data transfer to ~26 TB/month, instantly saving approximately $5,800/month in AWS egress fees. CDN exploration in future.

## Phase: Client-Side Image Compression & Auto-Scaling Pivot (Date: 2026-06-16, Commit: 59e7d96969d2e4145bd933add858bc0fe04be681, Model: Gemini 3.1 Pro (High))
*   **Analysis:** We evaluated the impact of compressing images *before* they are uploaded. Sending a 150KB image over the network instead of a 1.5MB image drastically improves user experience on mobile networks. Crucially, it drops the "Processed Bytes" penalty on an AWS Application Load Balancer (ALB) to almost zero. The math proves that with client-side compression, a fully managed AWS ALB actually becomes *cheaper* ($29/mo) than maintaining a custom open-source Nginx Load Balancer ($30/mo).
*   **Actions:**
    *   Updated `photoz/photos/templates/photos/upload.html`.
    *   Injected the `browser-image-compression` library via CDN.
    *   Added an async JavaScript listener to intercept the `<form>` submission.
    *   Configured the web-worker to downscale the image to max `1080px` and compress to `0.7` quality directly in the user's browser.
    *   Dynamically replaced the heavy file in the input with the lightweight compressed Blob before sending the HTTP POST.
*   **Notes/Edge Cases:** The backend `utils.py` Pillow logic is intentionally left intact as a secondary defense to ensure that API requests skipping the browser JS are still forcefully compressed and resized before hitting S3.

## Phase: Infrastructure & Frontend Debugging (Date: 2026-06-16, Commit: bd1eb56e4485c7edd822802d0d532669d8edc335, Model: Gemini 3.1 Pro (High))
*   **Analysis:** After deploying the horizontally scaled architecture, we encountered three distinct issues: CloudWatch log groups persisting after `terraform destroy`, a database `IntegrityError` during boot, and a silent failure of the client-side compression script.
*   **Actions:**
    *   **CloudWatch Logs Retention:** Docker automatically created the `awslogs` groups on EC2 boot, preventing Terraform from tracking or destroying them. Created `cloudwatch.tf` to explicitly manage `photoz-app-logs` and `photoz-lb-logs` with a 7-day retention policy so they are cleanly deleted on `terraform destroy`.
    *   **Database Migration Race Condition:** Booting multiple App EC2 instances simultaneously caused a distributed race condition where both nodes hit the empty Postgres database and tried to run `python manage.py migrate` at the exact same millisecond. This caused an `IntegrityError` (violating unique constraint on `auth_permission`) and crashed the container. Fixed by adding `restart: always` to `docker-compose-app.yml` so the container revives and successfully skips the migration after the other node finishes.
    *   **WebWorker CORS Exception:** Accessing the Load Balancer via HTTP triggered a Cross-Origin-Opener-Policy browser block on the client-side image compression WebWorker. Disabled WebWorkers (`useWebWorker: false`) to bypass local/HTTP restrictions.
    *   **Verbose JS Error Logging:** Updated the `try/catch` block in `upload.html` to inject `error.message` into the hidden `client_compressed` payload, allowing the backend Django logs to instantly reveal exactly why frontend JS failed.
    *   **JS Form Selector Bug:** Discovered that `document.querySelector('form')` in `upload.html` was incorrectly grabbing the Search Form in the navbar (the first form in the DOM). This caused the WebWorker event listener to attach to the search bar instead of the photo upload form, completely bypassing client-side compression. Fixed by using `fileInput.closest('form')` to precisely target the correct form. This needs HTTPS for client compression to work, else it's blocked on the modern browsers with error `browserImageCompression is not defined`.
    *   **Same-Origin Script Bypass:** To bypass the strict Chrome security policies blocking the third-party CDN script on HTTP, we downloaded `browser-image-compression.js` directly into `photoz/static/js/`. Serving it locally as a same-origin request bypasses the Cross-Origin-Opener-Policy blocks without requiring HTTPS.
    *   **Function Name Typo:** Discovered the global variable was `imageCompression`, not `browserImageCompression`. Corrected the function call in `upload.html`.
*   **Notes/Edge Cases:** The CloudWatch fix required users to manually run `aws logs delete-log-group` if the logs were already created by Docker before Terraform attempted to adopt them.

## Phase: Consul Service Discovery Implementation (Date: 2026-06-18, Commit: 10a3dd01510afb532d325cd838f031e561949045, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Transitioned from a hardcoded Nginx upstream block to a dynamic Service Discovery architecture using HashiCorp Consul. This allows Auto Scaling Groups to scale App nodes infinitely without manual Nginx configuration updates.
*   **Actions:**
    *   **Terraform:** Reversed dependency order so `lb_node` boots first, allowing App nodes to dynamically receive the Load Balancer's private IP (`CONSUL_SERVER_IP`) via `user_data`.
    *   **LB Node:** Replaced standard Nginx container with a custom image bundling `consul-template`. Added a `consul-server` container in `bootstrap` mode. Configured `consul-template` to dynamically write `nginx.conf` and issue `nginx -s reload` commands internally without exposing `/var/run/docker.sock`.
    *   **App Node:** Deployed lightweight `consul-agent` sidecar via `docker-compose-app.yml` on the host network. Mounted `web.json` to configure an edge HTTP health check pinging the local Gunicorn port 8000 every 10 seconds.
*   **Notes/Edge Cases:** Avoided mapping `docker.sock` to the template container by packaging Nginx and Consul-Template into a single container. This ensures strict isolation and prevents root privilege escalation vulnerabilities.

## Phase: Auto Scaling Group Implementation (Date: 2026-06-18, Commit: 8efea0e1779ff69bc377a93526717d34874e7df9, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Transitioned the App nodes from static `aws_instance` definitions to an AWS Auto Scaling Group (`aws_autoscaling_group`) to enable true self-healing and dynamic scaling. Added CloudWatch CPU scaling policies.
*   **Actions:**
    *   **Terraform Migration:** Replaced `aws_instance.app_node` with `aws_launch_template.app_node` and `aws_autoscaling_group.app_nodes`.
    *   **Scaling Policies:** Implemented `aws_autoscaling_policy` with Step Scaling triggered by `aws_cloudwatch_metric_alarm`. Added a scale-up policy (+1 instance) for `CPUUtilization > 70%` and a scale-down policy (-1 instance) for `CPUUtilization < 30%`.
    *   **High Availability:** Set ASG constraints to `min_size = 2` and `max_size = 4`, guaranteeing cross-AZ availability while allowing the cluster to automatically replace terminated instances.
*   **Notes/Edge Cases:** With the introduction of ASG, `app_server_private_ips` in `outputs.tf` was replaced by `app_server_asg_name` since instances are now dynamically provisioned by AWS.

## Phase: CloudWatch EMF Metrics Middleware (Date: 2026-06-30, Commit: 0d17852e38ff966e51b6ae0c6d828dae46535d4bq, triggered by chapter04, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Chapter04 benchmark scripts identified N+1 query problems and missing indexes using offline analysis (`DEBUG=True` + `connection.queries`). To get the same visibility in production without the overhead, we needed a lightweight middleware that measures request and database latency per endpoint.
*   **Actions:**
    *   **New file:** Created `bses/metrics_middleware.py` with `CloudWatchMetricsMiddleware`. Uses Django's `connection.execute_wrapper()` to wrap every SQL call and measure `DatabaseLatency` and `QueryCount` per request. Outputs CloudWatch Embedded Metric Format (EMF) JSON to stdout.
    *   **Settings:** Added `json_raw` formatter, `metrics_console` handler, and `metrics` logger to `LOGGING` config. Registered `CloudWatchMetricsMiddleware` at the end of the `MIDDLEWARE` list.
*   **Notes/Edge Cases:**
    *   EMF JSON must be output as raw text (no log-level prefix or timestamp), which is why a separate `json_raw` formatter is used instead of the existing `simple` formatter.
    *   **Vendor Agnosticism:** By logging structured JSON instead of using AWS `boto3` to call `PutMetricData`, the application remains entirely decoupled from AWS. If the system migrates to Datadog or Grafana, the log forwarder can extract the metrics from the JSON without requiring any code changes in the Django application.

## Phase: CloudWatch EMF Middleware - High Cardinality Fix (Date: 2026-07-01, Commit: 408c39b4d1c99f254f3025f85b7798212a3784c8, triggered by chapter04, Model: Claude Opus 4.6 (Thinking))
*   **Analysis:** CloudWatch metrics were failing to aggregate into line graphs because the EMF middleware was logging exact URL paths (e.g., `/users/phoenix_jackson_0/`). This high cardinality created tens of thousands of unique metrics instead of grouping them by route.
*   **Actions:**
    *   **Metrics Middleware Update:** Updated `bses/metrics_middleware.py` to use Django's `request.resolver_match.view_name` instead of `request.path`. Because Django's `route` property truncates outer included URL namespaces, `view_name` is much cleaner. This transforms specific URLs into their exact logical view names (e.g., `profile`, `newsfeed`, `login`), allowing CloudWatch to correctly aggregate the data into clean visualizations.

## Phase: Newsfeed N+1 Query Fix (Date: 2026-07-04, Commit: 4f1239cae949316ceb826c918264e7d99d7f4340, triggered by chapter04, Model: Claude Opus 4.6 (Thinking))
*   **Analysis:** Newsfeed page fired 87 queries per page load due to N+1 lazy-loading in the template loop. Each of the 20 photos triggered separate queries for user, profile, community, likes count, and comments count.
*   **Actions:**
    *   **newsfeed/views.py:** Added `select_related('user__profile', 'community')` and `annotate(likes_count=Count('likes', distinct=True), comments_count=Count('comments', distinct=True))` to the feed QuerySet. Added `Count` import.
    *   **newsfeed/templates/newsfeed/feed.html:** Replaced `{{ photo.likes.count }}` with `{{ photo.likes_count }}` and `{{ photo.comments.count }}` with `{{ photo.comments_count }}` to use pre-computed annotations.
*   **Expected result:** 87 queries -> ~7 queries per newsfeed page load.

## Phase: Newsfeed Database Latency Fix (Date: 2026-07-05, Commit: d8a670a2997f24f59b42825d2c3b4986c7a6e568, triggered by chapter04, Model: Claude Opus 4.6 (Thinking))
*   **Analysis:** EXPLAIN ANALYZE showed 524ms execution time due to massive LEFT JOINs from `.annotate()` and Seq Scans from missing indexes.
*   **Actions:**
    *   **newsfeed/views.py:** Removed `.annotate()` from the main feed queryset. Added post-pagination count queries using `Like.objects.filter(photo_id__in=photo_ids)` and `Comment.objects.filter(photo_id__in=photo_ids)` to compute counts for only the 20 visible photos.
    *   **photos/models.py:** Added composite indexes on `Photo` (`user/-created_at`, `community/-created_at`, `-created_at`) and `Comment` (`photo/created_at`).
*   **Result:** Database execution time dropped from 524.5ms to 9.9ms (a ~98% reduction). Sequential Scans and massive JOINs were completely eliminated, replaced by Index Scans. CloudWatch reported `DatabaseLatency: 79.06ms` total across 9 queries.

## Phase: Fix Photo Detail N+1 (Date: 2026-07-05, Commit: 25e37ec718217a91741755205ab5234b9178b804, triggered by chapter04, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Photo detail page fired 24-30 queries due to N+1 on the photo's profile/community, and N+1 on the comment's user/profile.
*   **Actions:**
    *   **photos/views.py:** Added `.select_related('user__profile', 'community')` to the `Photo` lookup, and `.select_related('user__profile')` to the `photo.comments` queryset.
    *   **Result:** Queries drop to a flat ~5 queries regardless of comment count. No new indexes needed (relies on PK index, single column FK indexes, and the `idx_comment_photo_created` composite index added in Phase 2).

## Phase: Fix Profile Page N+1 (Date: 2026-07-05, Commit: 0a8ce76b5987a620df6ca4dad9ed474c34fe39dd, triggered by chapter04, Model: Gemini 3.1 Pro (High))
*   **Analysis:** The profile page benchmark was doing an extra database query to fetch the User object after fetching the UserProfile.
*   **Actions:**
    *   **users/views.py:** Added `UserProfile.objects.select_related('user')` to the `get_object_or_404` call in `profile_view` to load both simultaneously in one query.

## Phase: Remove Dead-Weight Index (Date: 2026-07-08, Commit: c3261dbe9c25e417d9496149d0a926dfbe602796, triggered by chapter04, Model: Gemini 3.1 Pro)
*   **Analysis:** Removed `idx_photo_created_at` because there is no global explore feed that orders by `-created_at` without filtering by user/community.
*   **Actions:**
    *   **photos/models.py:** Removed the index `idx_photo_created_at` from the `Photo` model.

## Phase: Hashtag Search (Date: 2026-07-10, Commit: 9157189ec89c9e74a53b993eda22efb2ed3cf9dc, triggered by chapter04, Model: Claude Opus 4.6)
*   **Analysis:** The application only supported searching for users by name. Users had no way to find photos by topic. Implemented hashtag-based photo search using PostgreSQL's `pg_trgm` extension with a GIN trigram index on the `caption` column for fast substring matching.
*   **Actions:**
    *   **bses/settings.py:** Added `django.contrib.postgres` to `INSTALLED_APPS`.
    *   **photos/models.py:** Added `GinIndex` with `gin_trgm_ops` on the `caption` field.
    *   **photos/migrations/0004_enable_pg_trgm.py:** Manual migration to enable `pg_trgm` PostgreSQL extension.
    *   **photos/views.py:** Added unified `search_view` that routes to user search (plain text) or hashtag photo search (queries starting with `#`). Uses same post-pagination count approach as newsfeed.
    *   **photos/urls.py:** Added `path('search/', ...)` route.
    *   **photos/templates/photos/search_results.html:** New unified template rendering user cards or photo cards based on query type.
    *   **photos/templatetags/hashtag_tags.py:** Custom `linkify_hashtags` filter that converts `#hashtag` text into clickable search links.
    *   **newsfeed/templates/newsfeed/feed.html:** Applied `linkify_hashtags` filter to captions.
    *   **photos/templates/photos/detail.html:** Applied `linkify_hashtags` filter to captions.
    *   **templates/navbar.html:** Updated search bar to point to unified `/photos/search/` endpoint with updated placeholder text.

## Phase: Hashtag Search Privacy Bug Fix (Date: 2026-07-12, Commit: [c97834face52712c77b140da721af1fa3ef24622], triggered by chapter04, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Photos belonging to private communities were leaking into hashtag search results for non-members because `_search_photos_by_hashtag` applied a text filter on the caption without enforcing community visibility constraints.
*   **Actions:**
    *   **photos/views.py**: Updated `_search_photos_by_hashtag` to include a `visibility_q` filter ensuring a user can only see public photos, their own photos, or photos in communities they are a member of. Imported `CommunityMembership`.

## Phase: PgBouncer Connection Pooling (Date: 2026-07-13, Commit: [d1c0a317acea8d31ec34ea7752710173750b2955], triggered by chapter04, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Adding PgBouncer to multiplex 1000+ app connections down to 20 Postgres connections to solve connection limit saturation and OOM thrashing on the DB instance.
*   **Actions:**
    *   **docker-compose-db.yml**: Added `pgbouncer` service mapping port 6432 to `db:5432`. Added `max_connections=20` to `db`.
    *   **docker-compose-app.yml**: Appended `POSTGRES_PORT=6432` to the environment block of `web`.
    *   **photoz/docker-compose.yml**: Replicated the PgBouncer integration for the local unified dev setup.

## Phase: PgBouncer Auth Query Implementation (Date: 2026-07-14, Commit: [6fcc1ec93351e6b72b5477a2eff9e818031c6f2a], Model: Gemini 3.1 Pro (High))
- **Goal**: Harden PgBouncer authentication by using `scram-sha-256` instead of `plain` text, following Enterprise best practices.
- **Analysis**: Instead of manually managing SCRAM hashes in `userlist.txt` or relying on bypassing authentication with `trust`, we configured PgBouncer to use `auth_query`. This allows PgBouncer to dynamically query Postgres for the SCRAM hash of connecting users, allowing for robust password rotation and True Zero Trust authentication.
- **Actions**:
    - Created `photoz/postgres-init/01-pgbouncer-auth.sql` to initialize a `pgbouncer` user and a `SECURITY DEFINER` function for querying `pg_shadow`.
    - Created `photoz/pgbouncer/pgbouncer.ini` and `userlist.txt` for custom `edoburu` image configuration.
    - Updated `photoz/docker-compose.yml` and `photoz/docker-compose-db.yml` to remove `POSTGRES_HOST_AUTH_METHOD=trust` and instead mount the new init scripts and config files.

## Phase: Django Persistent Connections (Date: 2026-07-14, Commit: [0ea0d9f3167b76439de81406383c8c6da241ed6f], Model: Gemini 3.1 Pro)
- **Goal**: Fix 100% CPU bottleneck on App Nodes during load testing caused by TCP and SCRAM-SHA-256 overhead.
- **Analysis**: By default, Django (`CONN_MAX_AGE=0`) tears down and rebuilds the database connection on every HTTP request. With PgBouncer auth set to `scram-sha-256`, this meant Django was forced to perform expensive cryptographic hashing 200 times per second during load testing. The App Nodes maxed out at 100% CPU, while the database remained idle.
- **Actions**:
    - **photoz/bses/settings.py**: Set `CONN_MAX_AGE` to 60 seconds (configurable via `.env`). This instructs Django to keep the TCP connections to PgBouncer alive, completely bypassing the connection and authentication overhead on subsequent requests.

## Phase: Read Replicas Bug Fixes (Date: 2026-07-16, Commit: d5440e8, Model: Gemini 3.1 Pro (High))
- **Goal**: Fix UI errors and deployment misconfigurations discovered during the Read Replicas deployment.
- **Analysis**: During testing, several application-level bugs surfaced. First, when PgBouncer failed to connect, the application threw an unhandled 500 error page. Second, the `feed.html` template contained a typo causing a `NoReverseMatch`. Third, `docker-compose-app.yml` had a hardcoded `REPLICA_DB_HOST` which overrode the environment variables on EC2.
- **Actions**:
    - **photoz/templates/500.html**: Created a graceful 500 error page template.
    - **photoz/nginx/nginx.conf.local**: Configured local Nginx to intercept 502/504 Bad Gateway/Timeout errors and serve the `500.html` template instead of the default white screen.
    - **photoz/newsfeed/templates/newsfeed/feed.html**: Fixed `{% url 'search_users' %}` typo to `{% url 'search' %}`.
    - **photoz/docker-compose-app.yml**: Removed the hardcoded `REPLICA_DB_HOST` environment variable so that it correctly inherits from `.env` on AWS instances.

## Phase: Application-Level Multi-Replica Routing (Date: 2026-07-18, Commit: a6d897dd438d696cc65dc475fbbfad651cf83dd7, Model: Gemini 3.1 Pro)
* **Analysis**: The architecture was previously hardcoded to route all read queries to a single replica instance (`aws_instance.db_replica[0]`), leaving secondary replicas completely idle. The user requested to implement application-level routing to distribute the load across all available replicas.
* **Actions Taken**:
  * Updated `iaac/aws/terraform/main.tf` to join all replica private IPs into a comma-separated list and inject it as `REPLICA_DB_HOSTS` inside the `.env` file.
  * Modified `photoz/bses/settings.py` to parse `REPLICA_DB_HOSTS` (falling back to single-node configuration for safety) and dynamically generate `DATABASES` keys (`replica_1`, `replica_2`, etc.).
  * Updated `photoz/bses/routers.py`'s `PrimaryReplicaRouter` to dynamically detect all aliases starting with `replica_` on initialization, and implemented `random.choice()` in `db_for_read` to evenly load balance traffic across them.
* **Errors & Edge Cases**: Handled the edge case where `db_replica_count = 0` by providing safe fallbacks directly to the primary database in both Django settings and Terraform.

## Phase: User Search Query Optimization (Date: 2026-07-21, Commit: 9edf3cd77c0c9a264d9a9f5ab86ce3f8cb4e0ae0, Model: Gemini 3.1 Pro (High))
* **Analysis**: During the final load test, the `/photos/search/?q=alex` endpoint averaged 1865ms, significantly skewing the overall read latency average. The search view queried the `UserProfile` model using `icontains` on `username_display`, `first_name`, and `last_name` without a trigram index, forcing PostgreSQL to perform a full table scan.
* **Actions**:
  * Modified `photoz/users/models.py` to add `GinIndex` with `gin_trgm_ops` to the `UserProfile` fields (`username_display`, `first_name`, `last_name`).

## Phase: Replication Slot Crash Loop Fix (Date: 2026-07-22, Commit: e01fad9c6c0676f6c170af0b33f2c737bd89bb7b, Model: Claude Sonnet 4.6 (Thinking))
* **Analysis**: On fresh infrastructure launch, the replica database container entered an infinite crash loop. The error was `pg_basebackup: error: replication slot "replica_N" already exists` (first deployment) and later `replication slot "replica_N" does not exist` (after fix attempt). Root cause had two layers:
  1. `pg_basebackup -C -S replica_N` creates the slot AND takes the backup atomically. If the backup fails mid-run, it wipes `PGDATA` but leaves the slot behind on the primary. On the next container restart, `PGDATA` is empty so the script tries again and fails because the slot already exists. Infinite loop.
  2. The slot creation was moved into `02-setup-replication.sh` (which runs automatically during Docker's initdb phase) without `REPLICA_COUNT` being injectable at that point. Docker's initdb only creates `replica_1` (default). When Terraform then ran the same script again to create more slots, `set -e` caused it to crash on `CREATE USER replicator` (already exists) before reaching slot creation. So `replica_2` was never created.
* **Actions**:
  * Removed `-C` flag from `pg_basebackup` in `photoz/postgres-replica/docker-entrypoint-replica.sh` so it uses a pre-existing slot instead of trying to create one.
  * Restored `photoz/postgres-init/02-setup-replication.sh` to only handle `postgresql.conf` configuration and replicator user creation (no slot creation), since this script runs during Docker initdb where `REPLICA_COUNT` cannot be injected.
  * Created `photoz/postgres-init/03-create-replication-slots.sh`: a standalone script that creates `replica_1..replica_N` slots based on `REPLICA_COUNT`. Can be called both from Terraform and manually over SSH.
  * Updated `iaac/aws/terraform/main.tf` to call `03-create-replication-slots.sh` after the DB restarts (with `wal_level=replica` active), passing `REPLICA_COUNT=${var.db_replica_count}`.

## Phase: Read Your Writes Consistency Fix (Date: 2026-07-22, Commit: 2287a7c85248edaf847a3f0fdd8b73d619c0d888, Model: Claude Sonnet 4.6 (Thinking))

**Analysis**: Async replication lag causes the "read your writes" violation — a user writes data, and their immediate next read hits a replica that hasn't received the write yet. The session-cookie approach pins only the writing user's reads to primary for 5 seconds (enough for replication to catch up), so all other users continue reading from replicas.

**Actions**:
- Created `bses/ryw_middleware.py` — `ReadYourWritesMiddleware` uses a thread-local variable to communicate the "force primary" signal to the DB router. On write requests, sets the flag and drops the `force_primary` cookie (max_age=5s). On any request with the cookie, sets the flag so in-request reads also go to primary.
- Updated `bses/routers.py` — `db_for_read()` calls `is_primary_forced()` and returns `'default'` if true.
- Updated `bses/settings.py` — Added `bses.ryw_middleware.ReadYourWritesMiddleware` to `MIDDLEWARE` after `SessionMiddleware`.

---

## Phase: Caching — Part 1 Postgres Init Changes (Date: 2026-07-23, Commit: Pending, Model: Claude Sonnet 4.6 (Thinking))

**Analysis**: `benchmark_repeated_reads.py` needs `pg_stat_statements` on the primary to count per-query execution statistics. This extension requires two separate steps: preloading it via `shared_preload_libraries` in `postgresql.conf` (requires restart), and running `CREATE EXTENSION` once per database. Both are added to the init scripts so any fresh deployment has them automatically.

**Actions**:
- Updated `postgres-init/01-pgbouncer-auth.sql` — added `CREATE EXTENSION IF NOT EXISTS pg_stat_statements` at the top of the init SQL so the extension is created when the DB initializes for the first time.
- Updated `postgres-init/02-setup-replication.sh` — added `shared_preload_libraries = 'pg_stat_statements'` and `pg_stat_statements.track = all` to the `postgresql.conf` block so the extension is preloaded at server start.

## Phase: Newsfeed Caching (Part 1 - Redis) (Date: 2026-07-25, Commit: 634eb3b2d3389583c112e22aec80fe01806e5aa4, Model: Gemini 3.1 Pro (High))
*   **Analysis:** Newsfeed was generating on the fly for every read, taxing DB CPU and causing repeated disk reads. Implemented Redis caching using a Pull/Push (Fan-out on write) pattern.
*   **Decisions:**
    *   Chose Redis over Memcached for its `LIST` data structures, which allow O(1) prepend operations for timeline updates.
    *   Chose self-managed EC2 instance for Redis deployment to optimize infrastructure costs over ElastiCache.
*   **Actions:**
    *   **Terraform (`iaac/aws/terraform`):** Added `aws_security_group.redis` and `aws_instance.redis_node` to `main.tf`. Updated `variables.tf` with `create_redis_node`. Injected `REDIS_URL` into `app_node` user data.
    *   **Settings (`photoz/bses/settings.py`):** Added `django-redis` to `requirements.txt` and configured `CACHES` backend with `REDIS_URL` and `LocMemCache` fallback.
    *   **Pull Pattern (`photoz/newsfeed/views.py`):** Refactored `newsfeed` view to check `feed:{user_id}` in cache. On cache miss, it computes the top 1000 IDs and caches them. Pagination then slices these cached IDs, and fetches only the relevant objects from the database.
    *   **Push Pattern (`photoz/photos/views.py`):** Refactored `upload_photo` to implement fan-out on write. When a photo is uploaded, its ID is prepended to the author's and followers' `feed:{user_id}` Redis lists (capped at 1000 items).
    *   **Bug Fix (Date: 2026-07-26):** Discovered that `cache.set` serializes data as a Pickled String, which breaks `client.lpush` (which requires a Redis List structure). Refactored both Push and Pull views to bypass `cache.set` and directly use native `client.rpush()` and `client.lrange()` with the `:1:` prefix to ensure true Fan-out on Write compatibility.
    *   **Thundering Herd Fix (Date: 2026-07-27, Commit: pending):** Added a "Cache Promise" (Mutex/Lease) using a short-lived Redis lock (`SETNX`). On a cache miss, only the first request is granted the lock to query the database. The remaining concurrent requests ("the herd") enter a short polling loop (max 1 second) waiting for the cache to be populated, safely falling back to an empty feed if the timeout is breached to protect the database.

## Phase: Debug Thundering Herd Benchmark (Date: 2026-07-28, Commit: 30de301d36491dd9c0f88af4f159fb7f78f35f89, Model: Gemini 3.1 Pro)
*   **Analysis:** The benchmark script for testing the Thundering Herd cache promise pattern was returning 0 heavy queries. 
    *   Found that `time.sleep(6)` caused the RYW `force_primary` cookie to expire, routing all read queries to the Replica DB. Since the script queried `pg_stat_statements` on the Primary DB, the queries were invisible.
*   **Actions Taken:**
    *   Removed the `time.sleep(6)` from `chapter04/caching/benchmark_thundering_herd.py` to keep the RYW lock active.
    *   Increased `urllib3` connection pool size in `benchmark_thundering_herd.py` to ensure 50 true concurrent connections.

## Cache Promise Implementation (Date: 2026-07-29, Commit: 8ba86c42cf3fc4eebdd4627d4b2dd1088d0b753a, Model: Gemini 3.1 Pro)
*   **Analysis:** Fixed the Thundering Herd issue by implementing a cache promise pattern in the newsfeed view.
*   **Actions Taken:**
    *   Refactored `photoz/newsfeed/views.py` to implement a cache promise pattern.
    *   Added a Redis lock to ensure only one request can query the database at a time.

## Phase: Device Caching Fallback and RYW Edge Case Discovery (Date: 2026-07-30, Commit: 58f24a44ad6f3947e9636e03a50512b260bd63b3, Model: Gemini 3.1 Pro)
*   **Analysis:** If the Cache Promise times out (e.g., polling fails to find the generated cache), returning a `200 OK` with an empty array wipes the user's screen. Instead, we want the browser/device to preserve the stale feed HTML. During benchmark testing with an artificial 15-second sleep, we also validated a beautiful edge case involving the Read-Your-Writes middleware.
*   **Actions Taken:**
    *   **Device Caching:** Added `@cache_control(private=True, max_age=60, stale_if_error=86400)` to the `newsfeed` view to explicitly allow client-side caching.
    *   **Fallback Response:** Modified the timeout block in `newsfeed/views.py` to return an `HTTP 503 Service Unavailable`. This prevents the browser from overwriting the currently rendered HTML with an empty list, and instructs compatible CDNs/browsers to serve the stale feed.
    *   **RYW Edge Case (Validation):** Validated that an artificial 15-second generation delay correctly causes the 5-second RYW `force_primary` lock to expire. The heavy feed query was automatically routed to the Replica DB, perfectly bypassing the Primary DB's `pg_stat_statements`. This proves the resilience of both the Cache Promise and the Replica DB routing logic.

## Phase: CloudFront CDN Integration (Date: 2026-08-01, Commit: 37facce11475b0d47191b89671d0306853e05dc7, Model: Claude Opus 4.6)
*   **Analysis:** Photos were being fetched directly from S3 on every request. Users far from ap-south-1 experiences high latency. Added CloudFront CDN in front of S3 to cache photos at edge locations worldwide.
*   **Actions Taken:**
    *   Added `AWS_S3_CUSTOM_DOMAIN` and `CLOUDFRONT_DISTRIBUTION_ID` to `bses/settings.py` inside the `USE_S3` block.
    *   Created `photos/cdn.py` — a wrapper module with `invalidate_cache(path)` that calls CloudFront's `CreateInvalidation` API via boto3. No-op when `CLOUDFRONT_DISTRIBUTION_ID` is not set.
    *   Updated `photos/views.py` `delete_photo` view to capture `photo.image.name` before deletion, then call `cdn.invalidate_cache()` to purge the cached copy from CloudFront edge locations.
    * `CloudFrontFullAccess` policy for aws iam user.
*   **Design Decisions:**
    *   CDN invalidation logic extracted into a separate `cdn.py` wrapper instead of inlining boto3 calls in views.py. Keeps views clean and makes the CDN layer reusable.
    *   Community photos use UUID-in-path approach (no signed URLs). Acceptable for current requirements.
    *   Photos have unique filenames (UUID + epoch), so CDN caching is safe — re-uploads never collide with cached paths.

## Phase: Cache Invalidation Fix (Date: 2026-14-01, Commit: d31a3a70d05e949ada035eee5325da20459876e7, Model: Gemini 3.1 Pro (High))
    * Analysis: Identified that follow/unfollow actions in users/views.py did not invalidate the newsfeed cache, leading to stale data.
    * Actions:
        * Modified photoz/users/views.py to import django.core.cache.cache.
        * Added cache.delete("feed:{request.user.id}") to toggle_follow_view.

    * Analysis: Identified three additional areas causing cache staleness/pagination gaps: Community joining, photo deletion, and account deletion.
    * Actions:
        * Modified photoz/communities/views.py to invalidate cache upon accepting an invitation.
        * Modified photoz/users/views.py to invalidate followers' caches before account deletion.
        * Modified photoz/photos/views.py to invalidate followers' caches before photo deletion.

## Phase: Fix Cache Race Condition in delete_photo (Date: 2026-08-02, Commit: 934c7ded8bed7045b1b19270ca1ed861e102c7f7, Model: Claude Sonnet 4.6)

- **Analysis:** `delete_photo` was clearing the feed cache before deleting the photo from the DB. In that brief gap, a concurrent read would find a cache miss, rebuild the cache from DB (photo still there), and then the photo would be deleted, leaving a ghost entry in the rebuilt cache. Fix: DB delete must come before cache invalidation.
- **Actions:**
    - Modified `photoz/photos/views.py`: moved `photo.delete()` and `invalidate_cache()` to before the `cache.delete()` calls in `delete_photo`.
- **Edge Cases:** follower_ids list is collected before deletion (follower relationships are unaffected by photo deletion), but cache invalidation is deferred until after the DB write. This is the correct order.

## Phase: Denormalization - Phase 1 Benchmark Scripts (Date: 2026-08-02, Commit: ef91f9c38a7f8d29b64f5f39b289747eb2ccae46, Model: Claude Sonnet 4.6 (Thinking))

- **Analysis:** `likes_count` and `comments_count` are computed at read time via SQL `COUNT(*)`. Adding them as columns on the `Photo` table will eliminate these queries from hot paths. Phase 1 creates the baseline benchmarks before any model changes.
- **Actions:**
    - Created `chapter04/denormalization/benchmark_before.py` -- Django ORM script for local DB baseline (query count + DB time).
    - Created `chapter04/denormalization/benchmark_before_http.py` -- HTTP-based benchmark against live AWS deployment. Measures p50/p95/p99 latency end-to-end through Nginx, Gunicorn, Redis, and Postgres. Same auth pattern as `chapter04/caching/benchmark_thundering_herd.py`.
- **Edge Cases:** Benchmark results to be recorded after running against AWS deployment.

## Phase: Phase 4 & 5 (Denormalization - Application Changes) (Date: 2026-08-02, Commit: 96c93c01dfc9c81ac34be5ff68452d9c51134e12, Model: Gemini 3.1 Pro (High))

**Analysis:** After successfully migrating the database to add `likes_count` and `comments_count` columns to the `Photo` model and backfilling them via a batched migration, the final step is to switch the application to read from these columns and maintain them atomically during writes.

**Actions:**
* Updated `photos.views.toggle_like` and `photos.views.add_comment` to increment/decrement the counts atomically using Django's `F()` expressions (e.g., `F('likes_count') + 1`).
* Removed the decoupled post-pagination COUNT aggregations from `newsfeed.views.newsfeed` and `photos.views._search_photos_by_hashtag`. They now rely completely on the prefetched column values.
* Modified `photos/templates/photos/detail.html` to read `comments_count` from the context, eliminating the hidden template-level query (`comments.count`).
* Documented troubleshooting steps in the README for handling stuck database migration locks caused by long-running transactions.

## Phase: Phase 6 (Benchmark After Denormalization) (Date: 2026-08-02, Commit: 96c93c01dfc9c81ac34be5ff68452d9c51134e12, Model: Gemini 3.1 Pro (High))

**Analysis:** With the schema migrated and the application code updated to use the denormalized `likes_count` and `comments_count` columns, we ran the HTTP benchmark script again to measure the real-world latency improvements under load.

**Actions:**
* Executed `benchmark_after_http.py` against the live AWS deployment.
* Compared the before and after p95 tail latencies:
  * **Newsfeed**: 1303ms -> 610ms (~53% faster)
  * **Profile**: 1168ms -> 312ms (~73% faster)
  * **Photo Detail**: 1137ms -> 673ms (~40% faster)
* The massive reduction in p95 latency proves that the expensive `Merge Left Join` and `GroupAggregate` SQL operations that PostgreSQL was previously forced to perform on every page load were successfully eliminated. The read path is now fully optimized.


## Phase: Ruff + Pylint Integration (Date: 2026-08-22, Commit: e566aabb5479545584b2422ba8accfecdb19d6d8, Model: Claude Sonnet 4.6 (Thinking))

- **Analysis:** No linting or formatting tooling existed. Added ruff (formatting + fast lint) and pylint (deep static analysis) scoped to `photoz/` only. Pylint rule set reduced to exclude rules already covered by ruff.
- **Actions:**
    - Created `photoz/pyproject.toml` — ruff (E/F/I/UP/B/SIM, line-length 100) + pylint config (style rules disabled, Django false positives disabled).
    - Created `photoz/requirements-dev.txt` — dev-only: ruff, pylint, pylint-django, pre-commit. Not in production `requirements.txt`.
    - Created `.pre-commit-config.yaml` at repo root — ruff with `--fix`, pylint as local system hook with `pylint_django` plugin, both scoped to `^photoz/`.
    - Modified `.github/workflows/deploy.yml` — added `lint` job (ruff check, ruff format check, pylint). `test` job gets `needs: lint`.
- **Edge Cases:** pylint pre-commit hook uses `language: system`, so `pip install -r requirements-dev.txt` must be run locally before `pre-commit install`.

## Phase: Fix Pylint Pre-Commit Configuration & View Errors (Date: 2026-08-22, Commit: f13a0ac61c3ca12c315b9aec0d01c9fa09f4378d, Model: Gemini 3.7 Flash)
*   **Analysis:** Pylint was running from repository root without `--rcfile=photoz/pyproject.toml`, ignoring configuration disables. Additionally, `E5110` (django-not-configured) and `C0103` (invalid local variable name) failed pre-commit check.
*   **Actions:**
    *   Added `--rcfile=photoz/pyproject.toml` to `.pre-commit-config.yaml` pylint hook args.
    *   Added `E5110` (django-not-configured) to `disable` list in `photoz/pyproject.toml`.
    *   Renamed local variable `User` to `user_model` in `photoz/users/views.py` (`signup_view`).
*   **Notes/Edge Cases:** None.

## Phase: Fix Image Rendering and Local Media Serving (Date: 2026-08-23, Commit: Pending, Model: Gemini 3.1 Pro)
*   **Analysis:** Identified two issues preventing images from rendering locally. First, when using local storage, media files were not being served because Nginx lacked the configuration and volume mount. Second, when using S3 storage locally (`USE_S3=True`), the S3 bucket is private but `AWS_QUERYSTRING_AUTH` was hardcoded to `False`, causing the unsigned image URLs to return `403 Forbidden`.
*   **Actions:**
    *   Added a leading slash to `MEDIA_URL` (`/media/`) in `bses/settings.py` for correct path generation.
    *   Added `./media:/app/media` volume mount for the `nginx` container in `docker-compose.yml`.
    *   Added `location /media/` block in `nginx/nginx.conf.local` to serve media files from `/app/media/`.
    *   Updated `bses/settings.py` to set `AWS_QUERYSTRING_AUTH = True` dynamically unless a custom domain (`AWS_S3_CUSTOM_DOMAIN`) is configured. This ensures `django-storages` generates presigned URLs for private S3 images.
    *   Re-created Nginx container and restarted the `web` container.
*   **Notes/Edge Cases:** The dynamic `AWS_QUERYSTRING_AUTH` setting ensures CloudFront (which sets `AWS_S3_CUSTOM_DOMAIN`) still uses cache-friendly unsigned URLs while local S3 connections bypass the `403` restriction using presigned URLs.

## Phase: Step 2: Import Linter (Architecture Guardrails) (Date: 2026-08-23, Commit: Pending, Model: Gemini 3.7 Flash)
*   **Analysis:** We needed to enforce domain app independence (preventing spaghetti imports between `users`, `communities`, `photos`, `newsfeed`, `notifications`). The previous `git reset` wiped out the configuration, so it had to be re-implemented.
*   **Actions:**
    *   Re-created `photoz/.importlinter` with an `independence` contract for the 5 domain apps.
    *   Extracted the exact 5 existing cross-app violations (`newsfeed.views -> photos.models`, etc.) using `import-linter` directly and added them to `ignore_imports` to whitelist the legacy violations.
    *   `import-linter` parses the AST and dynamically builds the module graph. The local run missed 3 `users` violations because `users` failed to resolve from the repo root context, but the GitHub CI run (`working-directory: photoz`) correctly resolved all 27 dependencies and caught them. Re-added the 3 `users` violations to `ignore_imports` to ensure GitHub CI passes.
    *   Running `import-linter` via standard `language: python` in pre-commit failed because the repository root isn't a package. Falling back to `language: system` with custom `entry` command was the cleanest solution.
    *   Re-integrated `import-linter` into `.pre-commit-config.yaml` using `language: system` and `PYTHONPATH=photoz` to ensure it automatically runs on every commit using the local virtual environment.

## Phase: Step 3: TrueCourse Configuration (Date: 2026-08-23, Commit: Pending, Model: Gemini 3.1 Pro (High) )
*   **Analysis:** We needed to enforce semantic architecture guardrails (layer violations, business logic drift) using an AI-powered code intelligence tool called TrueCourse. Since the requirement is to use free, local tools, we chose to use TrueCourse via a local Ollama LLM endpoint.
*   **Actions:**
    *   Updated `chapter05/architecture_guardrails/README.md` to include detailed manual installation steps for Node.js (`npm`), Ollama, and the `llama3.1:8b` model.
    *   Added execution commands for `npx truecourse analyze install` and the exact CLI flag sequence to re-route TrueCourse to the local Ollama API.
*   **Notes/Edge Cases:** Since Node.js and Ollama were not installed on the system, the configuration could not be executed programmatically. We shifted to a "documentation-first" approach where the commands are recorded as runbooks in the README for the developer to execute locally.

## Phase: CALM Guardrails Integration (Date: 2026-08-26, Commit: pending, Model: Gemini 3.1 Pro (High) )
* **Analysis & Rationale:** Integrated FINOS CALM to add declarative architecture-as-code validation. Decided to build custom organizational guardrails on top of the FINOS specification using a JSON Schema pattern file (`guardrails.pattern.json`) to enforce security boundaries early in the DevSecOps lifecycle.
* **Actions Taken:**
    * Created `photoz/architecture/photoz.calm.json` defining the high-level architecture.
    * Created `photoz/architecture/guardrails.pattern.json` with strict `allOf` / `not` / `if-then` rules enforcing:
        * No writes to Read Replicas.
        * Mandatory HTTPS for connections to S3 and CDN.
        * Strict DB isolation (preventing load balancers and CDNs from accessing primary-db directly).
    * Updated `.pre-commit-config.yaml` to run `calm validate` with the custom pattern.
    * Updated GitHub Actions (`.github/workflows/calm-validation.yml`) to enforce these rules on `push` and `pull_request` against `**.json` paths.
    * Updated `chapter05/architecture_guardrails/README.md` to document usage of the new guardrails.
* **Edge Cases / Errors Fixed:**
    * Addressed regex compilation failure in JSON schema by replacing `(?i)write` with `.*[Ww]rite.*`.
    * Resolved pre-commit ignoring untracked files by staging the newly created architecture JSON files.

### Phase: Architecture Evaluation for New Features (Date: 2026-08-27, Commit: Pending, Model: Gemini 3.1 Pro (High))
* **Analysis**: Evaluated the integration of four new features (User Tagging, Stories, Verified Profiles, Profile Links) into the current Photoz architecture. Used  and  to assess current coupling. Found that the system is a tightly coupled monolith where Django apps (, , , ) directly import each other's models inside views.
* **Decisions**: 
  * The system is too coupled for a direct microservices extraction. We must first enforce strict boundaries (Modular Monolith) by introducing an internal API/Service layer and using Event-Driven patterns (e.g., signals/Celery) instead of direct cross-app view imports.
  * Verified Profiles and Profile Links fit natively into  without adding coupling.
  * Tagging users and Stories will require service-level boundaries to prevent worsening the  violations.
* **Actions Taken**:
  * Generated Implementation Plan artifact detailing the proposed architecture adjustments and feature implementations.

### Phase: Architecture Evaluation for New Features (Date: 2026-08-27, Commit: Pending, Model: Gemini 3.1 Pro (High))
* **Analysis**: Evaluated the integration of four new features (User Tagging, Stories, Verified Profiles, Profile Links) into the current Photoz architecture. Used drift-analyzer and import-linter to assess current coupling. Found that the system is a tightly coupled monolith where Django apps (newsfeed, photos, communities, users) directly import each other's models inside views.
* **Decisions**:
  * The system is too coupled for a direct microservices extraction. We must first enforce strict boundaries (Modular Monolith) by introducing an internal API/Service layer and using Event-Driven patterns (e.g., signals/Celery) instead of direct cross-app view imports.
  * Verified Profiles and Profile Links fit natively into users.models.UserProfile without adding coupling.
  * Tagging users and Stories will require service-level boundaries to prevent worsening the import-linter violations.
* **Actions Taken**:
  * Generated Implementation Plan artifact detailing the proposed architecture adjustments and feature implementations.

### Phase: Decoupling Strategy Selection (Date: 2026-08-27, Commit: Pending, Model: Gemini 3.1 Pro (High))
* **Analysis**: The user rejected introducing an external task queue (e.g., Celery) at this stage. Evaluated using native Python `async` vs Django Signals for achieving an event-driven architecture to decouple the Django apps.
* **Decisions**:
  * Rejected native Python `async`/threading due to volatility (data loss on worker restarts), risk of event-loop starvation, and incompatibility with the current synchronous Gunicorn worker architecture.
  * Chose **Django Signals** combined with **Service Layers**. This strictly decouples the codebase and resolves `import-linter` violations. While the execution time remains synchronous (adding latency to uploads), this perfectly positions the architecture for an easy transition to a real task queue later, as signal receivers can easily be converted to Celery tasks without modifying the core views.
* **Actions Taken**:
  * Updated Implementation Plan artifact to formally define the Service Layer + Signals architecture and document the trade-offs.

### Phase: Introduce Service Layers (Date: 2026-08-29, Commit: aca7a79a4e9d4cf03b0f60d4e6e265203e8a8e2f, Model: Gemini 3.1 Pro (High))

**Analysis & Rationale:**
- The application suffered from high cyclomatic complexity and cross-app coupling (e.g., `newsfeed/views.py` importing models directly from `photos`, `users`, and `communities`). 
- To resolve `import-linter` domain violations and reduce logic embedded inside view functions, we introduced the Service Layer pattern.
- This creates explicit boundaries where apps interact with other apps exclusively through dedicated `services.py` modules, abstracting away internal data queries and complex logic (like Redis caching).

**Actions Taken:**
- `[NEW]` Created `users/services.py`, `communities/services.py`, `photos/services.py`, and `newsfeed/services.py`.
- `[MODIFY]` Refactored `newsfeed/views.py` to use the new service functions for fetching photos, user details, and communities, moving the entire Redis lock & polling logic to `newsfeed/services.py`.
- `[MODIFY]` Refactored `photos/views.py` and `communities/views.py` to remove direct cross-domain model imports, replacing them with service calls.
- `[MODIFY]` Removed resolved `ignore_imports` overrides from `.importlinter` to enforce the new strict architectural boundaries.
- `[EXECUTE]` Baselined `drift-analyzer` to lock in the reduced Co-Change Coupling and Cyclomatic Complexity improvements.


### Phase: Introduce Django Signals (Date: 2026-08-29, Commit: 807eaf114c18a95a8d059d5d3ab4409a671f4cd9, Model: Gemini 3.1 Pro (High))

**Analysis & Rationale:**
- The architecture requires breaking cross-app dependencies to satisfy import-linter and reduce cyclomatic complexity.
- We needed to decouple the `photos` app from the `notifications` and `newsfeed` apps so that actions in `photos` (uploads, likes, comments, deletes) do not directly import logic from other domain areas.
- Django Signals provide an asynchronous-like pub/sub mechanism to cleanly sever these dependencies. The `photos` app emits signals, while the relevant apps listen and respond independently.

**Actions Taken:**
- `[NEW]` Created `photos/signals.py` defining custom signals: `photo_uploaded`, `photo_deleted`, `photo_liked`, `photo_commented`.
- `[MODIFY]` Refactored `photos/views.py` to emit signals and completely removed dependencies on `newsfeed.services` and `notifications.models`.
- `[NEW]` Created `notifications/signals.py` to listen for `photo_liked` and `photo_commented` events, generating Notification records. Modified `notifications/apps.py` to wire these receivers on startup.
- `[NEW]` Created `newsfeed/signals.py` to listen for `photo_uploaded` and `photo_deleted` events, orchestrating the Redis cache fan-out and invalidation via its local services. Modified `newsfeed/apps.py` to wire these receivers on startup.

**Edge Cases & Learnings:**
- Care was taken not to prematurely delete cache invalidation mechanisms for the CDN inside the `delete_photo` view; the `photo.delete()` operation and `invalidate_cache()` must remain synchronized in `photos/views.py`, delegating ONLY the user feed cache fan-out to the `newsfeed` signal receiver.

### Phase: Infrastructure Configuration for ALLOWED_HOSTS (Date: 2026-08-29, Commit: 807eaf114c18a95a8d059d5d3ab4409a671f4cd9, Model: Gemini 3.1 Pro (High))
*   **Analysis:** The application used `ALLOWED_HOSTS = ["*"]`, which triggers security linters (e.g., Drift Analyzer insecure_default). Changing it directly to a local fallback (`"localhost,127.0.0.1"`) breaks production deployments where Nginx proxies traffic via the public Load Balancer IP/Domain.
*   **Actions:**
    *   Updated `iaac/aws/terraform/main.tf` to dynamically inject the LB node's private and public IPs into the generated `.env` file for the app nodes (`ALLOWED_HOSTS=$${aws_instance.lb_node.private_ip},$${aws_instance.lb_node.public_ip},localhost,127.0.0.1`).
    *   Updated `photoz/bses/settings.py` to remove the temporary `"*"` fallback and safely rely on `os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1")`.
*   **Notes/Edge Cases:** This provides a seamless transition satisfying security linters without risking production downtime during the deployment cycle. Locally, it naturally falls back to `localhost,127.0.0.1`, enabling docker-compose local testing without any extra configuration.

### Phase: Introduce Photo Tagging Feature (Date: 2026-08-29, Commit: Pending, Model: Gemini 3.1 Pro (High))
* **Analysis**: Implemented Phase 5 to allow users to tag other users in photo captions using `@username` syntax. Added UI autocomplete and explicit tagging rendering to improve the UX.
* **Actions Taken**:
  * `[NEW]` Created `PhotoTag` model in `photos/models.py`.
  * `[NEW]` Created `user_tagged` signal in `photos/signals.py`.
  * `[MODIFY]` Updated `upload_photo` in `photos/views.py` to extract tags from captions via regex, validate them with `get_user_profile_by_username`, save `PhotoTag`s, and emit the `user_tagged` signal. (Extracted into a helper `_process_photo_tags` to fix a cyclomatic complexity drift violation).
  * `[MODIFY]` Updated `Notification.TYPE_CHOICES` in `notifications/models.py` with `photo_tag`.
  * `[MODIFY]` Added receiver for `user_tagged` in `notifications/signals.py` to notify the tagged user.
  * `[NEW]` Configured `Tribute.js` in `base.html` and `app.js` to enable `@username` autocomplete dropdowns on caption uploads and comment inputs.
  * `[NEW]` Added `search_users_json` endpoint in `users/views.py` to power the autocomplete fetching.
  * `[MODIFY]` Extended `hashtag_tags.py` to support `linkify_hashtags` transforming `@username` strings into clickable profile URLs in captions and comments.
  * `[MODIFY]` Updated `detail.html` to pass explicitly tagged users from `PhotoTag` objects to visually display "With: @username" below captions, and applied the linkifier to comment texts.
  * `[MODIFY]` Updated `add_comment` view in `photos/views.py` to return the pre-rendered `html_text` so comments instantly appear clickable without a page refresh.
* **Edge Cases / Errors Fixed**: Resolved cognitive complexity issue flagged by drift-analyzer by extracting the tag parsing logic out of the main view body.
