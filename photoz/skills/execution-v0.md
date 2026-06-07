# Execution Log - v0

## Phase: Setup Slow Upload Scenario
*   **Analysis:** Based on the scenario of showcasing Gunicorn's synchronous workers getting blocked by slow client uploads, we set up `simulate_slow_upload.py` and `test_responsiveness.py` to replicate the problem.
*   **Actions:**
    *   Cleaned up old documentation files from `skills/` directory (kept `SKILLS.md`).
    *   Updated `SKILLS.md` to reference `chapter01` for the initial architecture.
    *   Created `simulate_slow_upload.py` to send photo data extremely slowly.
    *   Created `test_responsiveness.py` to test basic API responsiveness.
*   **Notes/Edge Cases:** None encountered yet.

## Phase: Execute Slow Upload Scenario
*   **Analysis:** Analyzed the test results from the 3 slow upload clients running against the 3 Gunicorn workers. The test successfully proved the vulnerability of synchronous workers, showing a complete paralysis of the API (`Read timed out`).
*   **Actions:**
    *   Updated `simulate_slow_upload.py` and `test_responsiveness.py` to authenticate fully and mimic a real browser session.
    *   Added photo-upload population to the fast responsiveness test so the newsfeed had real data to query.
    *   Created `TESTING.md` in `chapter03/slow_application_server/` to document the testing setup, execution steps, and exact HTTP logs.
    *   Recorded the final test results in the markdown file showing the 3 workers being completely blocked.
*   **Notes/Edge Cases:** The slow connections were forcefully terminated around the 33-second mark (`[Errno 32] Broken pipe`). This is exactly expected and caused by Gunicorn's default 30-second worker timeout, which forces Gunicorn to kill and restart frozen workers.

## Phase: Nginx Implementation
*   **Analysis:** We removed direct public access to Gunicorn by taking away its port `80:8000` mapping, as Gunicorn is not designed to buffer network requests or protect against slow clients. We introduced an Nginx reverse proxy explicitly configured to buffer the request body (`client_body_buffer_size 20M;`) before forwarding the traffic to Gunicorn.
*   **Actions:**
    *   Removed `whitenoise` from `requirements.txt` and `settings.py` since Nginx now serves static files.
    *   Created `photoz/nginx/Dockerfile` and `photoz/nginx/nginx.conf`.
    *   Updated `docker-compose.yml` to include the new `nginx` service mapped to port `80`, routing traffic to the internal `web:8000` upstream.
    *   Rebuilt and restarted the Docker Compose cluster.
*   **Notes/Edge Cases:** 
    *   Nginx successfully isolates Gunicorn from network latency.
    *   **EC2 Docker Bug:** During testing on Ubuntu EC2, running `docker-compose down` occasionally threw a `permission denied` error preventing containers from stopping. This is a known AppArmor bug with snap-installed Docker. Resolved by restarting the daemon: `sudo systemctl restart snap.docker.dockerd`.

## Phase: Server Overload Simulation Setup
*   **Analysis:** We needed to replicate a scenario where a severely under-provisioned EC2 instance (represented by our Docker container) gets its CPU and RAM exhausted by concurrent requests, causing unresponsiveness.
*   **Actions:**
    *   Created `chapter03/server_overload/` directory to store load testing scripts.
    *   Added Docker deploy resource limits to `web` service in `docker-compose.yml` (`cpus: 0.3`, `memory: 250M`) to simulate a small machine.
    *   Created `simulate_high_load.py` to bombard the signup endpoint with hundreds of concurrent requests, starving the container of CPU and memory.
    *   Created `monitor_health.py` to repeatedly test the responsiveness of the web app.
*   **Notes/Edge Cases:** This sets up the environment to demonstrate vertical and horizontal scaling.

## Phase: Vertical Scaling (Simulation)
*   **Analysis:** We confirmed that the `0.3` CPU limit caused Gunicorn workers to hit 100% CPU utilization, creating a massive backlog of "zombie" requests and causing 502/timeout errors. To resolve this without architectural changes, we simulated a hardware upgrade (Vertical Scaling).
*   **Actions:**
    *   Updated `docker-compose.yml` to increase the `web` service limits from `cpus: 0.3` to `cpus: 2.0` and `memory: 250M` to `memory: 1G`.
*   **Notes/Edge Cases:** Vertical scaling is the simplest fix for an overloaded server because it requires zero code changes. However, it has physical limits (a machine can only be so large) and is prone to single points of failure.
