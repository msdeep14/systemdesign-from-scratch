# Chapter 6 Benchmarks: Asynchronous Processing

Identification and fixing asynchronous processing bottlenecks in the Photoz architecture.

## Setup & Benchmarks

To expose and test the asynchronous processing bottlenecks, run the following steps.

### 1. Seed Celebrity Users
Creating "celebrity" accounts with a large number of followers.
*(Note: This creates `@celeb_500k`, `@celeb_1m`, and `@celeb_2m` with the password `password123`. It takes several minutes to run as we bulk create users in batches to avoid locking the database and impacting live traffic.)*

From the `photoz/` directory, run the command inside the `web` container. For AWS, run the command on one of EC2 app node:
```bash
docker-compose exec web python manage.py seed_celebrity_users
```

### 2. Run Upload Benchmark
To observe the fan-out bottleneck, run the benchmarking script which logs in as each celebrity and simulates an image upload.

#### Running Locally
From the project root directory, point the script to your local server (make sure venv is activated):
```bash
python chapter06/benchmarks/upload_timing.py
```

#### Running on AWS
From your local machine, run the script and point it to your AWS load balancer's IP or domain:
```bash
python chapter06/benchmarks/upload_timing.py --host http://<your-load-balancer-ip>
```

### What to Look For in Logs
While the benchmark is running, check your terminal running `docker-compose up` or the local Gunicorn instance. 
Look for JSON metrics output containing `RequestLatency` and `DatabaseLatency`.

To easily filter these logs, you can run (inside photoz/ directory):
```bash
docker-compose logs -f web | grep "RequestLatency"
```
For the synchronous fan-out implementation, you will observe extremely high request latency or Gunicorn timeout errors (which defaults to taking longer than 120s for `@celeb_1m` and `@celeb_2m`).
