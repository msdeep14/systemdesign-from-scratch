# BSES v0 — Implementation Execution Log

This document records the actions taken, decisions made, thought processes, and errors resolved during the implementation of the BSES v0 social media web application.

---

## 1. Actions Taken (Phases 1-4)

### Phase 1: Project Scaffolding
- Initialized the Django project `bses` and created 5 distinct apps: `users`, `photos`, `newsfeed`, `communities`, and `notifications`.
- Configured `settings.py` for installed apps, static/media files, authentication URLs, and custom pagination (`BSES_PAGE_SIZE = 20`).
- Set up `requirements.txt` with Django, psycopg2-binary, Pillow, and gunicorn.
- Created infrastructure files: `Dockerfile`, `docker-compose.yml`, and `.dockerignore` for AWS EC2 deployment.
- Established the frontend design system by creating `base.html`, `navbar.html`, `style.css` (custom CSS variables, responsive design, glassmorphism UI), and `app.js` (toast management, mobile menu).

### Phase 2: User Component
- Implemented `UserProfile` (linked OneToOne with Django's `User`) and `Follow` models.
- Built a custom `signup_view` that handles unique `username_display` validation while auto-generating a unique internal Django username.
- Created `profile_view` to display user details, follower/following stats, and a photo grid.
- Implemented `edit_profile_view` and `delete_account_view`.
- Built `toggle_follow_view` as an AJAX endpoint to handle follow/unfollow actions without page reloads.
- Created a user search functionality.

### Phase 3: Photo Component
- Built `Photo`, `Like`, and `Comment` models.
- Implemented a robust `compress_photo()` utility in `photos/utils.py` that intercepts uploads, validates the 2MB size limit, converts images to RGB, and compresses them using Pillow (quality=85).
- Created a custom `photo_upload_path` to store images in user-specific folders (`photos/<user_id>/`) with UUID and epoch timestamps to prevent name collisions.
- Built `upload_photo` and `photo_detail` views, alongside AJAX-powered endpoints for liking (`toggle_like`) and commenting (`add_comment`).

### Phase 4: Newsfeed Component
- Designed the newsfeed query to aggregate photos from users the current user follows, communities they belong to, and their own posts.
- Applied `distinct()` and order by `-created_at` to ensure chronological consistency without duplicates.
- Implemented Django `Paginator` to handle infinite-scroll style page rendering in the frontend.
- Created the `feed.html` template with photo cards, inline comment counts, and interactive like buttons.

---

## 2. Errors Resolved

### Error 1: Docker Daemon Not Running
**Context:** When preparing the environment for the user to test the application locally, an attempt was made to spin up the PostgreSQL container using `docker compose up -d db`.
**Error:** `Cannot connect to the Docker daemon... Is the docker daemon running?`
**Resolution:** Since the user's local Docker daemon was not active and the primary goal was to allow immediate testing of the existing codebase, the `settings.py` was temporarily modified to fall back to Django's default `sqlite3` database. Migrations were then successfully applied locally.

### Error 2: URL Reverse Error on Signup
**Context:** After the user signed up and was redirected to the newsfeed, the application crashed with a `NoReverseMatch` error.
**Error:** `Reverse for 'list_communities' not found. 'list_communities' is not a valid view function or pattern name.`
**Resolution:** The `navbar.html` template included links to the Communities and Notifications pages. Because Phases 5 and 6 had not yet been executed, those URL patterns did not exist. To immediately unblock the user's testing, placeholder views and URL patterns were rapidly created and registered for both the `communities` and `notifications` apps.

### Error 3: Media Files Not Rendering in Development
**Context:** After successfully uploading an image, the image failed to display in the newsfeed and photo detail views.
**Error:** Broken image links on the frontend because Django's development server (`runserver`) does not serve user-uploaded media files by default.
**Resolution:** Updated the main `bses/urls.py` file to include `static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)` when `DEBUG = True`. This enabled Django to serve files from the `MEDIA_ROOT` directory during development.

---

## 3. Decisions Made & Thought Process

### 3.1 Model Dependencies and Migration Order
**Thought Process:** While implementing the `Photo` and `Notification` models, I realized they had foreign key dependencies on `Community` and `CommunityMembership`. If I ran `makemigrations` before those models existed, Django would throw an error.
**Decision:** I proactively created the baseline models for the `communities` app out of sequence, prior to running the initial database migrations, ensuring a smooth database setup.

### 3.2 Decoupling the Username
**Thought Process:** Django's default `User` model has specific constraints on the `username` field. Relying on it directly for public display names can cause friction if we want to implement different validation rules or allow username changes later.
**Decision:** I chose to generate a hidden, internal UUID string for Django's `User.username` during signup, and instead explicitly handle the public-facing username via the `username_display` field on the `UserProfile` model.

### 3.3 Prioritizing AJAX for Interactions
**Thought Process:** Standard form submissions for "likes" and "comments" cause full page reloads, which severely degrades the user experience of a modern social media feed.
**Decision:** Liking and commenting were implemented entirely via JavaScript `fetch()` calls communicating with Django `@require_POST` JSON endpoints. This allows the UI to update instantaneously (optimistic UI updates) while keeping the server logic clean.

### 3.4 Media Storage Path Strategy
**Thought Process:** Uploading all photos to a single `/media/photos/` directory would eventually lead to filesystem performance issues and name collision risks.
**Decision:** Implemented a dynamic upload path `photos/<user_id>/photo_<uuid>_<epoch>.jpg`. This segments files by user and guarantees uniqueness regardless of original filename.

## 1. Actions Taken (Phases 5-6)

### Phase 5: Community Component
- Created `Community` and `CommunityMembership` models (previously scaffolded, now fully integrated).
- Developed the `create_community` view, which automatically assigns the creator as an 'accepted' member with a 'creator' role.
- Implemented `list_communities`, which combines communities the user has joined and communities they've created uniquely.
- Built the `community_detail` view, which partitions the layout into a photo grid and a member list.
- Integrated the `upload_photo` functionality seamlessly so users can upload photos directly into a specific community context.
- Implemented `invite_member` and `respond_invitation` logic, allowing members to invite other users and generating a pending `CommunityMembership`.

### Phase 6: Notifications Component
- Developed a global `Notification` model with choices for `community_invite`, `photo_like`, and `photo_comment`.
- Registered `notifications.context_processors.unread_count` in `settings.py` so the navbar globally displays the user's unread notification badge.
- Built the `notification_list` paginated view to display all alerts in descending chronological order.
- Implemented `mark_read` and `mark_all_read` views as AJAX POST endpoints so notifications can be dismissed seamlessly without page reloads.
- Embedded action forms inside community invite notifications (Accept/Reject) within the notification feed.

---

## 2. Additional Errors Resolved

### Error 4: User Profile Link Not Resolving
**Context:** The "Profile" link in the navigation bar generated an error (`No UserProfile matches the given query`) when clicked.
**Error:** The navbar was generating the URL using `user.username` (which is the internal Django UUID generated during signup) instead of `user.profile.username_display`.
**Resolution:** Updated `navbar.html` to correctly reference `{% url 'profile' username=user.profile.username_display %}`.

## 3. Actions Taken (Phases 7-8)

### Phase 7: UI Polish
- **Responsive Design**: Integrated CSS media queries inside `style.css` so the grid layouts (photo grids, community list) stack vertically on mobile screens.
- **Empty States**: Developed robust empty states with muted icons and call-to-action buttons for the Newsfeed, Notifications, Profile photos, and Communities pages.
- **Micro-interactions**: Added CSS transitions for hover states (buttons, cards) and JavaScript-driven auto-dismissing toast notifications.

### Phase 8: Testing & Cleanup
- **Edge Cases Handled**:
  - Prevented users from following themselves or inviting themselves to communities.
  - Ensured users don't generate notifications for their own actions (e.g., commenting on their own photo).
- **Docker Readiness**: Updated `bses/settings.py` so the `DATABASES` configuration defaults to PostgreSQL pointing to the `db` host (for `docker-compose`) or `localhost` (for native development). Removed all legacy SQLite fallback logic to enforce environment parity.
- **Documentation**: Generated a comprehensive `README.md` with instructions for PostgreSQL local testing and AWS EC2 Docker deployment.

---

## 4. Final Deployment Debugging

### Error 5: Port 8000 Conflict & PostgreSQL Transition
**Context:** The user attempted to run the server locally but encountered an "Error: That port is already in use" message.
**Error:** The AI's background task was still occupying port `8000`. Concurrently, the transition back to PostgreSQL caused connection timeouts because the Docker database container hadn't fully initialized.
**Resolution:** Killed the background task to free the port. Triggered a `docker-compose up -d db` and waited for the `postgres:15` container to initialize. Successfully applied migrations against the new PostgreSQL database and restarted the Django server natively. The application now runs identically to its production specification.

---

## 5. Additional System Enhancements

### Task: Hourly Application Logging
**Context:** Needed a debugging mechanism that captures both successful actions and errors. The logs had to rotate hourly and not be tracked in git.
**Decision:** Configured a `TimedRotatingFileHandler` with `when='H'` in Django's `LOGGING` dictionary. The custom logger is explicitly configured to write to `logs/bses.log` (automatically rolled over hourly).
**Actions Taken:**
- Appended `logs/` to `.gitignore`.
- Created the `logs` directory on the local filesystem.
- Modified `bses/settings.py` to instantiate the rotating log handler.
- Injected `logger.info()` and `logger.warning()` into `users/views.py`, `photos/views.py`, `communities/views.py`, and `notifications/views.py` to log auth flows, object creation, logic validation errors, and unauthorized access attempts.

### Task: Production WSGI Configuration (Gunicorn)
**Context:** The `docker-compose.yml` was originally executing `python manage.py runserver` for the `web` container. This development server is single-threaded and insecure for production EC2 deployments.
**Decision:** Transitioned the `web` container startup command to use `gunicorn` (which was already scaffolded in `requirements.txt`).
**Actions Taken:**
- Modified `docker-compose.yml` to execute `gunicorn --bind 0.0.0.0:8000 --workers 3 bses.wsgi:application` instead of the development server, ensuring the application can handle concurrent production traffic effectively.

### Task: Production EC2 Deployment Planning & Port Mapping
**Context:** Needed an implementation plan for deploying the application to an AWS EC2 instance, restricted by SSH to the local machine, but accessible on the web.
**Decision:** Planned the architecture around a `t3.micro` instance (Ubuntu 24.04). Devised security group rules to lock SSH (Port 22) to the user's specific public IP (`59.99.189.135/32`) and open Port 80 to `0.0.0.0/0`.
**Actions Taken:**
- Authored the deployment steps into an implementation plan.
- Updated `docker-compose.yml` to map the container port `8000` to the host's port `80` (`80:8000`), allowing standard HTTP web access without specifying a port.
- Updated `README.md` to reflect the new port 80 mapping.

### Task: Static Files Resolution under Gunicorn (WhiteNoise)
**Context:** When transitioning to Gunicorn, the Django application stopped serving static files (CSS/JS) because Gunicorn does not natively serve them.
**Decision:** Integrated `whitenoise` to allow Gunicorn to serve static files efficiently without the need for an external Nginx container, keeping the deployment architecture extremely simple.
**Actions Taken:**
- Added `whitenoise>=6.0.0` to `requirements.txt`.
- Added `whitenoise.middleware.WhiteNoiseMiddleware` to `MIDDLEWARE` in `bses/settings.py` immediately following the `SecurityMiddleware`.
- Rebuilt the Docker container.

### Task: Media Files Volume Masking Resolution
**Context:** Photos uploaded during earlier local testing were returning `404 Not Found` in the Docker container because the named volume `media_volume:/app/media` was masking the host's existing `./media` directory.
**Decision:** Dropped the named `media_volume` to rely purely on the global `.:/app` bind mount. Since `/media/` is in `.gitignore`, this directory acts as a persistent file store natively on the host filesystem both in local development and production.
**Actions Taken:**
- Removed `media_volume:/app/media` and the global `media_volume` definition from `docker-compose.yml`.
- Recreated the Docker web container to pick up the native host media directory.

---

*Log generated during Additional Enhancements completion.*
### Task: EC2 Instance Sizing & SSH "Connection Refused" Resolution
**Context:** During the manual deployment, an attempt was made to deploy the application onto a `t2.nano` (512 MB RAM) instance to minimize costs. This resulted in an immediate `Connection refused` error on Port 22 when attempting to SSH into the instance via both the terminal and AWS EC2 Instance Connect.
**Decision:** Investigated the boot constraints of modern Ubuntu AMIs. Diagnosed that 512 MB of RAM is insufficient for the Ubuntu boot sequence (`cloud-init`, `snapd`, etc.), causing the Linux kernel's Out-of-Memory (OOM) killer to terminate the SSH daemon (`sshd`) during boot. Furthermore, 512 MB is insufficient to run the Docker daemon, PostgreSQL, and Django simultaneously.
**Actions Taken:**
- Advised terminating the `t2.nano` instance.
- Verified that upgrading to a `t3.micro` (1 GB RAM) correctly allows the OS to boot, the SSH daemon to initialize, and provides the minimum necessary memory threshold to run the containerized Docker stack securely.

---
### Task: Django Allowed Hosts Resolution for EC2
**Context:** When successfully hitting the EC2 machine via its public IP, Django rejected the request with a `DisallowedHost` error because the EC2 IP wasn't present in `ALLOWED_HOSTS`.
**Decision:** Updated `ALLOWED_HOSTS = ['*']` to safely allow dynamic AWS Public IPs to serve the application without crashing.
**Actions Taken:**
- Modified `bses/settings.py` to allow all hosts.

---

## 6. Vercel Deployment Support

### Task: Vercel Configuration & Serverless Compatibility
**Context:** The application needs to be deployable on Vercel, a serverless platform. Vercel imposes restrictions such as an ephemeral filesystem and requires explicit WSGI handlers and build scripts.
**Decision:** Configured `vercel.json` to route all traffic to the WSGI application and handle static files via a custom `build.sh` script. Integrated `django-storages` for AWS S3 to support persistent media storage on Vercel.
**Actions Taken:**
- Created `vercel.json` to configure the `@vercel/python` builder and route requests.
- Created `build.sh` to install requirements, collect static files, and run database migrations during the Vercel build phase.
- Modified `bses/wsgi.py` to expose `app = application` to satisfy Vercel's Python runtime expectations.
- Modified `bses/settings.py` to add `.vercel.app` to `ALLOWED_HOSTS`.
- Modified `bses/settings.py` to conditionally load `django-storages` and `boto3` configurations if `AWS_STORAGE_BUCKET_NAME` is detected in the environment.
- Added `django-storages` and `boto3` to `requirements.txt`.

### Task: Docker Compose Security Refactor
**Context:** The `docker-compose.yml` file contained hardcoded PostgreSQL credentials, presenting a severe security risk if the repository was cloned to an EC2 instance or made public.
**Decision:** Extracted the hardcoded secrets from `docker-compose.yml` into a `.env` file to ensure they are excluded from version control.
**Actions Taken:**
- Modified `docker-compose.yml` to read `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` from environment variables.
- Generated a local `.env` file with the default connection credentials.
- Verified that `.env` was already ignored in `.gitignore`.

### Task: Vercel Python Runtime Alignment
**Context:** The `vercel.json` was initially configured for Python 3.10, but the local development environment relies on Python 3.12.
**Decision:** Updated the Vercel runtime configuration to match the local environment to prevent unexpected syntax or dependency mismatches in production.
**Actions Taken:**
- Modified `vercel.json` to specify `"runtime": "python3.12"`.

### Task: Vercel Architecture Diagram
**Context:** The project included an EC2 architecture diagram, but lacked visual documentation for the new serverless architecture.
**Decision:** Created a Mermaid-based architecture diagram to clearly illustrate the decoupled nature of Vercel Serverless Functions, AWS S3, and the remote PostgreSQL database.
**Actions Taken:**
- Authored `docs/vercel_architecture.md` containing a Mermaid flowchart.
- Rendered an AI-generated graphical architecture diagram, complete with a "nano banana", saved at `docs/vercel_architecture_diagram.png`.
