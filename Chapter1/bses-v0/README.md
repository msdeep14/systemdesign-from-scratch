# BSES v0 - Social Media Application

BSES is a modern, responsive social media web application built with Django. It features photo sharing, community creation, real-time-feel interactions (AJAX likes and comments), and a global notification system.

## Features

- **User Accounts**: Custom signup flow using hidden UUID usernames for system stability and explicit display usernames for URLs. Follow/unfollow functionality.
- **Photos**: Upload photos (auto-compressed to enforce 2MB limits), like, and comment.
- **Newsfeed**: Paginated global feed merging followed users' posts and community posts.
- **Communities**: Create and join niche communities. Upload photos exclusively to a community context. Invite other members.
- **Notifications**: Centralized alerts for community invites, photo likes, and comments.

## Local Development Setup

1. **Clone and create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start PostgreSQL Database**:
   The application strictly enforces PostgreSQL. Start the background database container:
   ```bash
   docker-compose up -d db
   ```

4. **Run migrations**:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

5. **Start the Gunicorn WSGI Server**:
   Instead of the Django development server, run the production Gunicorn server locally:
   ```bash
   gunicorn --bind 0.0.0.0:8000 --workers 3 bses.wsgi:application
   ```
   Visit `http://localhost:8000` in your browser.

## Start Everything via Docker (All-in-one)
If you don't want to start the database and Gunicorn manually as shown above, you can run everything together in one command using Docker. This will boot both the PostgreSQL database and the Django Gunicorn server simultaneously:
```bash
docker-compose up -d --build
```
You can then visit `http://localhost` (or your EC2 public IP) in your browser.

To stop the cluster:
```bash
docker-compose down
```

## Production Deployment (AWS EC2 / Docker)

This repository includes a `Dockerfile` and `docker-compose.yml` pre-configured for a production-like PostgreSQL setup.

1. **Start the application cluster**:
   ```bash
   docker-compose up -d --build
   ```

   This spins up two containers:
   - `db`: PostgreSQL 15 database.
   - `web`: The Django application running via Gunicorn (or management server).

2. **Access the application**:
   The application will be exposed on port `80` of your host machine.

3. **Database Inspection**:
   To view the raw data directly inside your running PostgreSQL container, make sure you are inside the `bses-v0` directory, then run:
   ```bash
   cd ~/bses-v0  # Ensure you are in the project folder
   docker-compose exec db psql -U postgres -d bses
   ```
   *Useful `psql` commands once inside:*
   - `\dt` : List all tables
   - `\d <table_name>` : View table schema
   - `SELECT * FROM users_user;` : Run a standard SQL query
   - `\q` : Quit and return to bash

4. **Stopping the cluster**:
   ```bash
   docker-compose down
   ```
