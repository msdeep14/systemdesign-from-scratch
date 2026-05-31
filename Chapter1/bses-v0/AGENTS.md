# AI Agent Instructions for BSES (AGENTS.md)

This document contains the core architectural decisions, coding standards, and execution mandates for the BSES Social Media Application. **All AI coding agents MUST read and adhere to these guidelines when making modifications or additions to the codebase.**

## 1. Execution Logging Mandate (CRITICAL)
Whenever you perform analysis, make architectural/design decisions, or take implementation actions, **you MUST append a log of your work to `execution-v0.md`**.
Your entry should include:
- The phase or feature you are working on.
- Brief analysis and the rationale behind any technical decisions made.
- A bulleted list of specific actions taken (files created, models updated, bugs resolved).
- Any notable edge cases or errors you encountered and how you fixed them.

## 2. Coding Standards
- **Keep it Simple & Direct**: Do not over-engineer. Do not abstract for the sake of abstraction. If a feature can be implemented cleanly in 10 lines instead of 100, choose the 10-line approach.
- **Strict Scope**: Do not add features or "future-proofing" abstractions that are not explicitly required for the current version.
- **Self-Documenting Code**: Avoid unnecessary comments. Code structure, method names, class names, and database schemas should be self-explanatory. Only add comments for highly complex logic.
- **Standard Django Conventions**: Follow idiomatic Django practices (e.g., standard fat models/thin views where applicable, robust form validation, standard routing).
- **RESTful Principles**: Ensure any API endpoints or AJAX-facing views are clean and follow RESTful principles.
- **Ask for Clarification**: Do not make blind assumptions. If the user's request is ambiguous or underspecified, stop and ask for clarification.

## 3. Architecture & Design Specifications
- **Stack**: Django (Monolith), PostgreSQL, Vanilla HTML/CSS/JavaScript.
- **Component Modularity**: The system is partitioned into domain-specific Django apps:
  - `users`: Auth, profiles, follow logic, search.
  - `photos`: Uploads, likes, comments.
  - `newsfeed`: Aggregation logic for timeline generation.
  - `communities`: Niche groups, memberships, invites.
  - `notifications`: Centralized global alerts.
- **Authentication & Usernames**:
  - The internal `User.username` is a hidden `UUID4` to ensure system stability and prevent clashes.
  - The public-facing username is stored in `UserProfile.username_display`. All URL routing (e.g., `/users/<username>/`) MUST use `username_display`.
- **Media Uploads**:
  - Photos must be validated (2MB size limit), compressed (Pillow, quality=85), and converted to RGB upon upload.
  - Upload paths must follow the pattern: `photos/<user_id>/photo_<uuid4>_<epoch>.<ext>` to absolutely guarantee collision prevention.
- **Database & Deployment**: 
  - The application strictly uses **PostgreSQL**. Do not configure SQLite fallbacks unless explicitly instructed.
  - The environment expects deployment via Docker (`docker-compose.yml`).
- **UI/UX Aesthetics**:
  - **Premium & Modern**: The interface must look visually stunning. Utilize clean typography, soft shadows, glassmorphism (where appropriate), and vibrant but soothing color palettes.
  - **Dynamic Interactivity**: Use CSS transitions for hover states and micro-animations. Actions like 'Like', 'Comment', 'Follow', and 'Read Notifications' should be asynchronous (AJAX) to prevent full page reloads.
  - **Responsive**: The design must follow a mobile-first approach but scale elegantly to desktop resolutions (e.g., stacking grids).
  - **Empty States**: Ensure all lists/feeds have robust, visually appealing empty states (e.g., "No posts yet") rather than blank screens.
