# Implementation Plan - v0

## Phase: Gunicorn Slow Photo Uploads & Nginx

### The Problem
Gunicorn uses synchronous workers by default. If a user on a slow network uploads a large file, the worker is blocked reading the incoming request body. Multiple slow clients can exhaust all available workers, rendering the application unresponsive.

### The Solution (Pending)
Nginx buffers request bodies asynchronously. It can receive the slow upload while Gunicorn remains free. Once fully received, Nginx passes the request to Gunicorn over the fast local network.

### Current Implementation Steps
1. Replicate the problem using `simulate_slow_upload.py` (which intentionally sends data in tiny chunks with long sleeps).
2. Measure responsiveness with `test_responsiveness.py`.
3. (Future) Implement Nginx to resolve the issue.
