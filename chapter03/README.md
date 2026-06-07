# Chapter 3: Concurrency and Scalability

This chapter explores two massive real-world system design challenges: handling slow I/O connections (network bottlenecks) and handling CPU exhaustion (viral traffic spikes). We demonstrate how different architectures (Nginx vs. Gunicorn, Vertical vs. Horizontal Scaling) handle these scenarios.

---

## Part 1: Slow Application Server (I/O Bottlenecks)

Located in `slow_application_server/`, these scripts demonstrate how a synchronous application server (like Gunicorn) behaves when clients have extremely slow network connections, and how a reverse proxy (Nginx) solves the problem via buffering.

### The Scripts
1. **`simulate_slow_upload.py`**
   Simulates a malicious or extremely slow user (like a 2G mobile connection) uploading a file one byte at a time to tie up the server's worker threads.
   ```bash
   python chapter03/slow_application_server/simulate_slow_upload.py <host_ip> <port>
   
   # Example:
   python chapter03/slow_application_server/simulate_slow_upload.py 13.206.208.79 80
   ```

2. **`test_responsiveness.py`**
   A monitor script that pings the server normally to see if it is still responsive for other users while the slow uploads are occurring.
   ```bash
   python chapter03/slow_application_server/test_responsiveness.py <host_ip>
   ```

**For full details on the test cases, Nginx configuration, and results, read:** [slow_application_server/TESTING.md](slow_application_server/TESTING.md)

---

## Part 2: Server Overload (CPU Bottlenecks)

Located in `server_overload/`, these scripts demonstrate how to exhaust a server's physical CPU using highly computational tasks (password hashing), and how to resolve the bottleneck using Vertical and Horizontal scaling.

### The Scripts
1. **`simulate_high_load.py`**
   Simulates a viral traffic spike by sending massive batches of concurrent signup requests, forcing the server to compute thousands of Argon2 password hashes.
   ```bash
   python chapter03/server_overload/simulate_high_load.py <host_ip> <port> <concurrent_workers>
   
   # Example (Simulate 50 concurrent users):
   python chapter03/server_overload/simulate_high_load.py 13.206.208.79 80 50
   ```

2. **`monitor_health.py`**
   A health check script with a strict 5-second timeout to monitor if the server is dropping requests or throwing `504 Gateway Timeouts` due to the CPU queue being backed up.
   ```bash
   python chapter03/server_overload/monitor_health.py <host_ip> <port>
   ```

**For full details on the Vertical Scaling thresholds, the Single-Node Horizontal Scaling lockup, and Stage 2 planning, read:** [server_overload/TESTING.md](server_overload/TESTING.md)
