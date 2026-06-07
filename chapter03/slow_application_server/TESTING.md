# Server Responsiveness & Reverse Proxy Analysis

This directory contains scripts and documentation demonstrating the vulnerability of synchronous web servers (like Gunicorn) to "slow client" attacks, and how to permanently mitigate the issue using a buffering reverse proxy (Nginx).

## 1. The Problem: Synchronous Workers
By default, Gunicorn uses `sync` workers. If configured with `--workers 3`, the server can only handle exactly 3 concurrent requests. 
When a client on a slow network (e.g., bad 3G) uploads a 1.9MB file at a painfully slow speed (like 8KB/sec), it takes several minutes to finish. Because the worker is synchronous, it must sit idle and wait for every single byte to arrive over the network before it can process the request. 
If 3 slow users upload photos at the same time, **100% of the server's workers are paralyzed**. Any new, fast requests (like loading the newsfeed) will hang indefinitely and eventually time out.

## 2. Exploring Gunicorn Alternatives (Async & Threads)
Before jumping to a reverse proxy, we explored native Gunicorn solutions:
*   **Threads (`--threads 10`):** Adds multi-threading to each worker, allowing 3 workers to handle 30 requests. This delays the paralysis but doesn't solve it (an attacker just needs 30 slow connections instead of 3).
*   **Async Workers (`gevent` / `eventlet`):** Changes the worker class to use non-blocking I/O. When a connection is waiting on slow network data, the worker yields and serves other requests. While this prevents the immediate lockup, it forces the Python application to hold thousands of sockets and memory buffers open, exposing it to memory exhaustion. Gunicorn's official documentation strongly advises against facing the open internet directly.

## 3. The Solution: Nginx Reverse Proxy
To permanently fix this, we implemented **Nginx** as a buffering reverse proxy. Nginx is built in C with an asynchronous, event-driven architecture capable of handling tens of thousands of connections effortlessly.

### The Role of the Reverse Proxy
1. **Isolation:** Gunicorn is no longer exposed to the internet. It only listens on the internal Docker network.
2. **Buffering:** We configured Nginx to absorb the slow upload. Nginx reads the incoming data byte-by-byte at whatever slow speed the client dictates, buffering it into memory or temporary files. Gunicorn is completely unaware this is happening.
3. **Lightning Fast Handoff:** Only when Nginx receives the *absolute final byte* of the 1.9MB upload does it forward the complete payload to Gunicorn over the internal network in a fraction of a millisecond. The Python worker processes the upload and is freed instantly.

### Code Changes Implemented
To achieve this architecture, the following code changes were made:
1. **Isolated Gunicorn:** Removed the `ports: ["80:8000"]` mapping from the `web` container in `docker-compose.yml`.
2. **Added Nginx Container:** Created an `nginx` service in Docker Compose bound to port `80`, routing traffic to the internal `web:8000` upstream.
3. **Nginx Configuration (`nginx.conf`):** 
   - Added `client_max_body_size 20M;` to allow large uploads without throwing a 413 error.
   - Added `client_body_buffer_size 20M;` to explicitly force Nginx to buffer the entire body into memory before passing it to the upstream.
4. **Static Files:** Nginx is vastly superior at serving static files. We removed the `whitenoise` Python library from `requirements.txt` and `settings.py`, and configured Nginx to serve the `/app/staticfiles/` directory directly.

---

## 4. Testing & Results

We used two scripts to prove the architecture:
*   `simulate_slow_upload.py`: Authenticates and uploads a 1.9MB photo byte-by-byte at an agonizing 8KB/sec.
*   `test_responsiveness.py`: Authenticates, uploads 3 tiny photos instantly, and measures how fast the newsfeed loads.

### Phase 1: Without Nginx (Direct Gunicorn)
- **Action:** We launched 3 slow uploads simultaneously.
- **Slow Client Result:** Gunicorn's default 30-second timeout kicked in. After ~33 seconds (at 270,336 bytes), Gunicorn assassinated the frozen workers, resulting in a `[Errno 32] Broken pipe` error for the slow clients.
- **Fast Client Result:** While the 3 uploads were running, the fast client completely failed to connect: `Read timed out. (read timeout=5)`. The server was totally paralyzed.

### Phase 2: With Nginx Reverse Proxy
- **Action:** We launched the exact same 3 slow uploads against Nginx.
- **Fast Client Result:** While the slow uploads were trickling in, the fast client was run. It received a `200 OK` response in **0.008 seconds**. The server was completely unfazed.
- **Slow Client Result:** Because Nginx was handling the connections, the 30-second Gunicorn timeout never triggered (since Gunicorn hadn't even seen the requests yet). The slow uploads successfully trickled data for over 4 minutes until they reached `1,992,294 bytes`. Once complete, Nginx handed them to Gunicorn in milliseconds, and the slow clients successfully received a `200 OK` HTML response!

**Conclusion:** Nginx successfully protected the synchronous Python workers, guaranteeing 100% uptime for normal users while safely and successfully accommodating users on terrible network connections!
