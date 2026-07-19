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
