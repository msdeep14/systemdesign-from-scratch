# BSES-v0 Project Skills & Architecture Summary

This document serves as the high-level context and project-specific skill set for AI agents working on the `bses-v0` project. 
For global repository rules (e.g., execution logging, general coding standards), refer to the root `AGENTS.md`.

## 1. Architectural Documentation Map

The initial architectural design, EC2 deployment setup, and foundational bootstrapping logs for this codebase are documented in the `chapter01/bses-v0/skills/` directory. Refer to that folder for the original designs. 
For scenarios and features added in this chapter, documentation will be captured in `implementation-v0.md` and `execution-v0.md` within this directory.

## 2. Project-Specific Logic & Constraints

When developing features for `bses-v0`, strictly adhere to the following architectural and design rules:

### Tech Stack
- **Backend**: Django (Monolith)
- **Database**: PostgreSQL strictly (no SQLite fallbacks)
- **Frontend**: Server-rendered templates with Vanilla HTML / CSS / JavaScript (No React/Vue).
- **Environment**: Docker & `docker-compose`.

### Component Modularity
The application logic is heavily decoupled into domain-specific Django apps:
- `users`: Auth, profiles, follow logic, user search.
- `photos`: Upload logic, image compression, likes, comments.
- `newsfeed`: Aggregation queries for timeline generation.
- `communities`: Niche groups, memberships, invites.
- `notifications`: Centralized global alerts (supports multiple content types).

### Authentication & Usernames
- **Internal Usernames**: Django's native `User.username` is overridden behind the scenes with a hidden `UUID4` to prevent clashes.
- **Public Usernames**: The public-facing username is stored in `UserProfile.username_display`. All URL routing (e.g., `/users/<username>/`) MUST query against `username_display`.

### Media Uploads & S3
- **Validation**: All uploaded photos must be validated (2MB size limit), converted to RGB, and compressed using Pillow (quality=85) before saving.
- **Paths**: Upload paths must follow the pattern: `photos/<user_id>/photo_<uuid4>_<epoch>.<ext>` to guarantee absolute uniqueness.
- **Storage Backend**: The application supports dynamic storage backends. It checks `USE_S3`. If True, it uses `django-storages` with `boto3` for S3 uploads (using `AWS_S3_ENDPOINT_URL` to prevent region signature mismatches). If False, it falls back to local disk (`MEDIA_ROOT`).

### UI/UX Aesthetics
- **Premium & Modern**: The interface must look visually stunning. Utilize clean typography (e.g., Inter), soft shadows, glassmorphism UI cards, and vibrant but soothing color palettes.
- **Dynamic Interactivity**: Forms like 'Like', 'Comment', 'Follow', and 'Read Notifications' must be asynchronous (via AJAX `fetch` calls) to prevent full page reloads.
- **Responsive**: The design must stack elegantly on mobile screens.
- **Empty States**: Ensure all lists/feeds have visually appealing empty states (e.g., "No posts yet") rather than rendering blank elements.
