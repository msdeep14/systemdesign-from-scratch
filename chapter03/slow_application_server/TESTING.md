# Slow Application Server Testing Guide

This directory contains scripts designed to simulate and test the behavior of a synchronous web server (like Gunicorn) under the load of "slow clients." 

Specifically, it demonstrates how a few users uploading photos on a very slow internet connection (e.g., a bad 3G network) can completely paralyze a server that relies on synchronous workers.

## Prerequisites

1. Ensure the `photoz` application is running (e.g., via `docker-compose up -d --build`).
2. Ensure you have the `requests` library installed in your local Python environment:
   ```bash
   pip install requests
   ```

## How to Test

### 1. Test Normal Responsiveness
First, verify that the server is responding quickly under normal conditions. 
Run the responsiveness script, providing your server's IP address (use your EC2 Public IP if testing remotely, or `127.0.0.1` for local testing):

```bash
python test_responsiveness.py <SERVER_IP>
```
*Expected Result:* You should see a `SUCCESS` message indicating the response took a fraction of a second.

### 2. Launch the Slow Client Attack
Gunicorn is currently configured with exactly 3 workers (`gunicorn --workers 3`). To tie up all workers, you need to spawn 3 slow uploads simultaneously.

Open **three separate terminal windows**, navigate to this directory, and run the following command in each one:
```bash
python simulate_slow_upload.py <SERVER_IP>
```
*What happens:* The script registers a dummy user, grabs a valid session, and starts uploading a 1.9MB photo at an agonizingly slow speed of 8KB/sec.

### 3. Verify Server Paralysis
While the three slow uploads are running in the background, open a **fourth terminal** and run the responsiveness test again:
```bash
python test_responsiveness.py <SERVER_IP>
```
*Expected Result:* The request will hang and eventually time out. All 3 Gunicorn workers are blocked reading the slow uploads, leaving no workers available to handle your fast request.

---

## Test Results Log

*Log your actual test results below after running the scenario.*

### Test Date: `[YYYY-MM-DD]`
**Environment:** `[Local / EC2 t3.micro]`
**Server IP:** `[IP Address]`

#### Baseline Responsiveness
- **Time Taken:** `[e.g., 0.142 seconds]`
- **Status:** `[e.g., 200 OK]`

#### Under Load (3 Slow Uploads)
- **Slow Upload 1 Status:** `[e.g., Uploading at 8192 bytes/sec]`
- **Slow Upload 2 Status:** `[e.g., Uploading at 8192 bytes/sec]`
- **Slow Upload 3 Status:** `[e.g., Uploading at 8192 bytes/sec]`
- **Responsiveness Test Result:** `[e.g., ERROR: Request timed out after 5.000 seconds! The server is blocked.]`

#### Observations & Conclusion
`[Add any notes about server CPU/Memory usage or application behavior during the test.]`
