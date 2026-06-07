# Server Overload & Scaling Simulations

This document records the sequence of load tests and architectural changes performed to demonstrate server overload, vertical scaling, and horizontal scaling.

## 1. Initial Setup: The Overloaded Server

**Objective:** Simulate an under-provisioned server being crushed by CPU-heavy tasks.
- **Docker Configuration:** 
  - `cpus: 0.3`
  - `memory: 250M`
  - `gunicorn --workers 3`
- **Action:** Ran `simulate_high_load.py` with 7 concurrent workers submitting CPU-intensive signup requests (password hashing).
- **Observation:** `docker stats` showed the `web` container hitting `30%` CPU utilization, which perfectly equals 100% of its `0.3` allowed limit. 
- **Result:** Because Gunicorn only had 3 workers, the remaining 4 requests sat in Nginx's waiting queue. The CPU was throttled so heavily that hashing took too long, causing requests to sit in the queue longer than the 5-second timeout. `monitor_health.py` began throwing constant `504 Gateway Timeout` errors.
- **Operational Fix:** We learned that running `docker compose restart web` forcefully drops the stuck "zombie" connections and instantly clears the Nginx queue, restoring the server.

---

## 2. Vertical Scaling

**Objective:** Scale "up" by simulating a hardware upgrade to a larger machine.
- **Docker Configuration:**
  - `cpus: 2.0`
  - `memory: 2G`
  - `gunicorn --workers 5` (Crucial: Application tuned to utilize the new cores via `2*cores + 1`)
- **Action (Test 1):** Ran the load test with 7 concurrent workers again.
- **Result:** Success. The `monitor_health.py` stayed completely green (`OK`). The 2 full cores and 5 workers chewed through the password hashes rapidly before the 5-second timeout could hit.
- **Action (Test 2 - Viral Traffic):** Ran the load test with 50+ concurrent workers.
- **Result:** Failure. `docker stats` showed the CPU hitting **198%** (fully saturating both cores). Even a large, vertically scaled machine has physical limits and was crushed by the massive traffic spike, resulting in timeouts.

---

## 3. Horizontal Scaling - Stage 1 (Docker Replicas)

**Objective:** Scale "out" by spinning up multiple identical containers on the *same* machine.
- **Docker Configuration:**
  - `deploy.replicas: 3` (3 identical `web` containers)
  - Limits per container: `cpus: 2.0`, `memory: 1G`
  - Nginx automatically load-balances across the 3 replicas via Docker internal DNS.
- **Action:** Ran the load test with 50+ concurrent workers on a physical AWS `t3.micro` EC2 instance.
- **Result:** The entire physical EC2 machine locked up and became completely unresponsive, hitting >90% physical CPU utilization.
- **Analysis:** By launching 3 containers with limits of 2.0 CPUs and 1G RAM each, we allowed Docker to consume up to 6.0 CPUs and 3GB RAM. However, a `t3.micro` only possesses 2 physical vCPUs and 1GB RAM total. The 3 containers fought to the death over the same 2 limited cores, causing massive starvation and OS lockup. **Adding containers on the same machine does not magically create more physical CPU cores.**
- **The Fix:** To stabilize the `t3.micro`, we tuned the container limits down to fit the physical host (`cpus: 0.5`, `memory: 200M`, `workers: 2` per replica). This safely distributed the load across 3 containers without exceeding the physical capacity of the machine.

---

## 4. Horizontal Scaling - Stage 2 (Multiple EC2 Instances)

**Objective:** Break out of the single-machine boundary to achieve true horizontal scaling.
- **Analysis:** Once the physical limits of the single EC2 host are exhausted, Stage 1 scaling is no longer viable. 
- **Next Steps:** The architecture must be split across entirely separate physical EC2 machines (e.g., Node 1 as a dedicated Load Balancer and Database, Node 2 and Node 3 as App Servers).
