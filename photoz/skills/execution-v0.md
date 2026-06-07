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
