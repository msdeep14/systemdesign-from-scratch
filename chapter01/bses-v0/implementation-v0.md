# BSES v0 — Implementation Plan

A social media web application where users upload photos and share them with followers. Built as a Django monolith with PostgreSQL, server-rendered HTML/CSS/JS frontend, mobile-first responsive design.

---

## Resolved Decisions

> Answers to initial design questions — incorporated throughout the plan below.

1. **Media storage** — Local filesystem (`MEDIA_ROOT`) on EC2. Photos stored in user-specific folders with naming pattern `photos/<user_id>/photo_<uuid4>_<epoch>.<ext>`. Photo file paths stored in PostgreSQL.
2. **Authentication** — Django's built-in `auth` (session-based login/logout/signup). No social login or token-based auth in v0.
3. **Notifications** — In-app notification model only. No email notifications. Notification is a **global component** (separate `notifications` app) supporting multiple types: `community_invite`, `photo_like`, `photo_comment`.
4. **Photo limits** — Max 2 MB per photo. Server-side compression applied on upload using Pillow before saving to disk.
5. **Pagination** — 20 items per page (configurable via `BSES_PAGE_SIZE` in `settings.py`).
6. **Deployment** — AWS EC2 with Docker. Django app and PostgreSQL run as separate Docker containers on the same EC2 instance. A `Dockerfile` and `docker-compose.yml` will be included.

---

## Proposed Architecture

```
bses-v0/
├── manage.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── bses/                        # Django project package
│   ├── settings.py              # includes BSES_PAGE_SIZE, media config
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── users/                       # User component (Django app)
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── forms.py
│   └── templates/users/
├── photos/                      # Photo component (Django app)
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── forms.py
│   ├── utils.py                 # compress_photo(), photo_upload_path()
│   └── templates/photos/
├── newsfeed/                    # Newsfeed component (Django app)
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   └── templates/newsfeed/
├── communities/                 # Community component (Django app)
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── forms.py
│   └── templates/communities/
├── notifications/               # Notification component (Django app) — global
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── context_processors.py   # unread_count for navbar badge
│   └── templates/notifications/
├── static/                      # Global static assets
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   └── app.js
│   └── img/
├── templates/                   # Base & shared templates
│   ├── base.html
│   ├── navbar.html
│   └── 404.html
└── media/                       # User-uploaded files (gitignored)
    └── photos/                  # Organized as photos/<user_id>/photo_<uuid4>_<epoch>.<ext>
```

Five Django apps — four functional components from the spec plus a shared `notifications` app that serves all notification types globally.

---

## Database Schema

### `users` app

#### UserProfile (extends Django `auth.User` via OneToOne)

| Column           | Type                      | Constraints                     |
|------------------|---------------------------|---------------------------------|
| id               | BigAutoField (PK)         | auto                            |
| user             | OneToOneField → auth.User | CASCADE, related_name="profile" |
| username_display | CharField(50)             | unique, indexed                 |
| first_name       | CharField(100)            | required                        |
| last_name        | CharField(100)            | blank, optional                 |
| profile_picture  | ImageField                | upload_to="profiles/", blank, optional |
| interests        | TextField                 | blank, optional                 |
| bio              | TextField                 | blank, optional                 |
| created_at       | DateTimeField             | auto_now_add                    |
| updated_at       | DateTimeField             | auto_now                        |

> **Design decision**: `username_display` is the public-facing unique username from the spec. We keep it separate from `auth.User.username` to decouple login identity from display identity. Login uses `auth.User.username` (which is set to the same value on signup but managed by Django auth), while `username_display` is used in URLs, profiles, and search.

#### Follow

| Column      | Type                  | Constraints                          |
|-------------|-----------------------|--------------------------------------|
| id          | BigAutoField (PK)     | auto                                 |
| follower    | ForeignKey → auth.User| CASCADE, related_name="following"    |
| following   | ForeignKey → auth.User| CASCADE, related_name="followers"    |
| created_at  | DateTimeField         | auto_now_add                         |

- **Unique constraint**: `(follower, following)` — prevents duplicate follows.
- **Check constraint**: follower ≠ following — can't follow yourself.

---

### `photos` app

#### Photo

| Column      | Type                   | Constraints                        |
|-------------|------------------------|------------------------------------|
| id          | BigAutoField (PK)      | auto                               |
| user        | ForeignKey → auth.User | CASCADE, related_name="photos"     |
| community   | ForeignKey → Community | SET_NULL, null, blank, optional     |
| image       | ImageField             | upload_to=`photo_upload_path`, required |
| caption     | TextField              | blank, optional                    |
| created_at  | DateTimeField          | auto_now_add                       |

- If `community` is NULL → personal post (shows in followers' feeds).
- If `community` is set → community post (shows in community members' feeds).

**Media storage strategy**:
- `upload_to` uses a callable `photo_upload_path(instance, filename)` that returns `photos/<user_id>/photo_<uuid4>_<epoch>.<ext>`.
- Since `photo_id` is not available before save, the pattern uses a UUID4 prefix instead of photo_id.
- Max file size enforced at **2 MB** via form validation (`PhotoUploadForm.clean_image()`).
- Server-side **compression** on upload: Pillow opens the image, converts to RGB if needed, and saves as JPEG at quality=85 (or keeps PNG if transparency is needed). This runs in the view before `model.save()`.

```python
# photos/utils.py — compression helper
def compress_photo(image_file, max_size_mb=2, quality=85):
    img = Image.open(image_file)
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    output = BytesIO()
    img.save(output, format='JPEG', quality=quality, optimize=True)
    output.seek(0)
    return InMemoryUploadedFile(
        output, 'ImageField', f"{image_file.name.rsplit('.', 1)[0]}.jpg",
        'image/jpeg', output.getbuffer().nbytes, None
    )
```

#### Like

| Column   | Type                   | Constraints                    |
|----------|------------------------|--------------------------------|
| id       | BigAutoField (PK)      | auto                           |
| user     | ForeignKey → auth.User | CASCADE                        |
| photo    | ForeignKey → Photo     | CASCADE, related_name="likes"  |
| created_at | DateTimeField        | auto_now_add                   |

- **Unique constraint**: `(user, photo)` — one like per user per photo.

#### Comment

| Column   | Type                   | Constraints                       |
|----------|------------------------|-----------------------------------|
| id       | BigAutoField (PK)      | auto                              |
| user     | ForeignKey → auth.User | CASCADE                           |
| photo    | ForeignKey → Photo     | CASCADE, related_name="comments"  |
| text     | TextField              | required                          |
| created_at | DateTimeField        | auto_now_add                      |

---

### `communities` app

#### Community

| Column      | Type                   | Constraints                          |
|-------------|------------------------|--------------------------------------|
| id          | BigAutoField (PK)      | auto                                 |
| name        | CharField(150)         | required                             |
| description | TextField              | blank, optional                      |
| creator     | ForeignKey → auth.User | CASCADE, related_name="created_communities" |
| created_at  | DateTimeField          | auto_now_add                         |

#### CommunityMembership

| Column      | Type                    | Constraints                              |
|-------------|-------------------------|------------------------------------------|
| id          | BigAutoField (PK)       | auto                                     |
| community   | ForeignKey → Community  | CASCADE, related_name="memberships"      |
| user        | ForeignKey → auth.User  | CASCADE, related_name="community_memberships" |
| role        | CharField(20)           | choices: `creator`, `member`             |
| status      | CharField(20)           | choices: `pending`, `accepted`, `rejected` |
| invited_at  | DateTimeField           | auto_now_add                             |
| responded_at| DateTimeField           | null, blank                              |

- **Unique constraint**: `(community, user)` — one membership record per user per community.

---

### `notifications` app (global)

#### Notification

| Column      | Type                    | Constraints                          |
|-------------|-------------------------|--------------------------------------|
| id          | BigAutoField (PK)       | auto                                 |
| recipient   | ForeignKey → auth.User  | CASCADE, related_name="notifications"|
| sender      | ForeignKey → auth.User  | CASCADE, related_name="sent_notifications", null, optional |
| type        | CharField(30)           | choices: `community_invite`, `photo_like`, `photo_comment` |
| message     | TextField               | auto-generated based on type         |
| photo       | ForeignKey → Photo      | SET_NULL, null, optional             |
| membership  | ForeignKey → CommunityMembership | SET_NULL, null, optional    |
| is_read     | BooleanField            | default=False                        |
| created_at  | DateTimeField           | auto_now_add                         |

> **Design decision**: Notification is a global component in its own Django app. It uses nullable ForeignKeys (`photo`, `membership`) instead of Django's `GenericForeignKey` — simpler to query, filter, and doesn't require `ContentType` lookups. The `type` field determines which FK is populated:
> - `community_invite` → `membership` is set, `photo` is NULL
> - `photo_like` → `photo` is set, `membership` is NULL
> - `photo_comment` → `photo` is set, `membership` is NULL
>
> A `sender` field tracks who triggered the notification (e.g., who liked/commented/invited). This allows rendering "**User X** liked your photo" without an extra query.

**Notification creation** happens inline in the relevant views (not via signals — keeps it explicit and simple):
- `photos/views.py → toggle_like()`: creates `photo_like` notification for photo owner
- `photos/views.py → add_comment()`: creates `photo_comment` notification for photo owner
- `communities/views.py → invite_member()`: creates `community_invite` notification for invitee

No notification is created when a user interacts with their own content (self-like, self-comment).

---

### `newsfeed` app

No dedicated database models. The newsfeed is constructed via queries:

```python
# Pseudocode for newsfeed construction
followed_users = Follow.objects.filter(follower=request.user).values_list('following', flat=True)
my_communities = CommunityMembership.objects.filter(user=request.user, status='accepted').values_list('community', flat=True)

feed = Photo.objects.filter(
    Q(user__in=followed_users, community__isnull=True) |  # posts from followed users
    Q(community__in=my_communities)                        # posts from my communities
).order_by('-created_at')
```

No pre-computed feed table. Simple query with pagination. This is the simplest approach and works well at this scale.

---

## API / URL Design

All views are Django template views (server-rendered). AJAX endpoints return JSON for like/unlike toggle and comment submission to avoid full page reloads on interactions.

### `users` app — `/users/`

| Method | URL Pattern                    | View              | Description                        |
|--------|--------------------------------|-------------------|-------------------------------------|
| GET    | `/signup/`                     | signup            | Registration form                  |
| POST   | `/signup/`                     | signup            | Create account (validates unique username) |
| GET    | `/login/`                      | login             | Login form                         |
| POST   | `/login/`                      | login             | Authenticate                       |
| POST   | `/logout/`                     | logout            | Log out                            |
| GET    | `/users/<username>/`           | profile           | View user profile (public)         |
| GET    | `/users/<username>/edit/`      | edit_profile      | Edit profile form (own profile)    |
| POST   | `/users/<username>/edit/`      | edit_profile      | Update profile                     |
| POST   | `/users/<username>/delete/`    | delete_account    | Delete account                     |
| POST   | `/users/<username>/follow/`    | toggle_follow     | Follow/unfollow (AJAX)             |
| GET    | `/users/search/`               | search_users      | Search by username or name         |

### `photos` app — `/photos/`

| Method | URL Pattern                    | View              | Description                        |
|--------|--------------------------------|-------------------|-------------------------------------|
| GET    | `/photos/upload/`              | upload_photo      | Upload form                        |
| POST   | `/photos/upload/`              | upload_photo      | Save photo (validates 2MB + compresses) |
| GET    | `/photos/<id>/`                | photo_detail      | View single photo with likes/comments |
| POST   | `/photos/<id>/delete/`         | delete_photo      | Delete own photo                   |
| POST   | `/photos/<id>/like/`           | toggle_like       | Like/unlike (AJAX, returns JSON)   |
| POST   | `/photos/<id>/comment/`        | add_comment       | Add comment (AJAX, returns JSON)   |

### `communities` app — `/communities/`

| Method | URL Pattern                            | View                  | Description                      |
|--------|----------------------------------------|-----------------------|-----------------------------------|
| GET    | `/communities/`                        | list_communities      | List user's communities          |
| GET    | `/communities/create/`                 | create_community      | Create form                      |
| POST   | `/communities/create/`                 | create_community      | Save community                   |
| GET    | `/communities/<id>/`                   | community_detail      | View community & its photos      |
| POST   | `/communities/<id>/invite/`            | invite_member         | Send invitation                  |
| POST   | `/communities/<id>/respond/`           | respond_invitation    | Accept/reject invite             |
| GET    | `/communities/<id>/upload/`            | upload_community_photo| Upload form for community photo  |
| POST   | `/communities/<id>/upload/`            | upload_community_photo| Save community photo             |

### `notifications` app — `/notifications/`

| Method | URL Pattern                            | View                  | Description                      |
|--------|----------------------------------------|-----------------------|-----------------------------------|
| GET    | `/notifications/`                      | notification_list     | View all notifications (paginated) |
| POST   | `/notifications/<id>/read/`            | mark_read             | Mark single notification as read (AJAX) |
| POST   | `/notifications/read-all/`             | mark_all_read         | Mark all notifications as read (AJAX) |

### `newsfeed` app — `/`

| Method | URL Pattern | View     | Description                              |
|--------|-------------|----------|------------------------------------------|
| GET    | `/`         | newsfeed | Home page — paginated feed from follows + communities |

---

## Frontend / Templates

### Base Layout (`templates/base.html`)
- Responsive navbar: logo, search bar, nav links (Feed, Upload, Communities, Notifications 🔔 with unread badge, Profile), logout
- Mobile: hamburger menu
- Global notification bell in navbar shows unread count (injected via Django context processor `notifications.context_processors.unread_count`)
- Footer (minimal)

### Design System (`static/css/style.css`)

| Aspect            | Choice                                                                 |
|-------------------|------------------------------------------------------------------------|
| Typography        | Google Fonts — **Inter** (clean, modern, excellent readability)        |
| Color palette     | Soft, soothing tones — muted indigo primary, warm neutrals, subtle gradients |
| Layout            | CSS Grid + Flexbox, mobile-first breakpoints                          |
| Cards             | Rounded corners, subtle shadows, glassmorphism on key surfaces        |
| Animations        | CSS transitions on hover/focus, smooth fade-in for feed items         |
| Dark/Light        | Light mode default (dark mode can be added later if desired)          |

### Key Templates

| Template                          | Description                                              |
|-----------------------------------|----------------------------------------------------------|
| `templates/base.html`            | Shell with navbar, footer, toast notifications           |
| `users/signup.html`              | Registration form with live username-availability check  |
| `users/login.html`               | Login form                                               |
| `users/profile.html`             | Profile page: avatar, bio, stats, photo grid, edit/delete buttons |
| `users/edit_profile.html`        | Edit form (no username change)                           |
| `users/search_results.html`      | Search results with user cards                           |
| `photos/upload.html`             | Drag-and-drop upload with preview                        |
| `photos/detail.html`             | Full photo view, likes counter, comments thread          |
| `newsfeed/feed.html`             | Infinite-scroll or paginated card feed                   |
| `communities/list.html`          | User's communities grid                                  |
| `communities/create.html`        | Create community form                                   |
| `communities/detail.html`        | Community page: info, members, photo grid                |
| `notifications/list.html`        | All notifications — like, comment, invite — with actions |

### JavaScript (`static/js/app.js`)

Vanilla JS — no frameworks. Handles:
- AJAX like/unlike toggle (updates count without reload)
- AJAX comment submission (appends comment to thread)
- Mobile nav hamburger toggle
- Username availability check on signup (debounced)
- Image preview on upload
- Notification badge count (polls or updates on interaction)
- Mark notification as read / mark all as read

---

## Execution Phases

### Phase 1: Project Scaffolding
- [ ] `django-admin startproject bses .`
- [ ] Create all five apps: `users`, `photos`, `newsfeed`, `communities`, `notifications`
- [ ] Configure `settings.py`: installed apps, database (PostgreSQL), static/media dirs, auth settings, `BSES_PAGE_SIZE = 20`
- [ ] Set up `requirements.txt`: Django, psycopg2-binary, Pillow
- [ ] Create `Dockerfile` and `docker-compose.yml` (Django + PostgreSQL containers)
- [ ] Create base template and static file structure
- [ ] Design system CSS (colors, typography, spacing, components)

### Phase 2: User Component
- [ ] `UserProfile` model + migrations
- [ ] `Follow` model + migrations
- [ ] Signup view with unique username validation
- [ ] Login / Logout views
- [ ] Profile view (public, shows photos + follower/following counts)
- [ ] Edit profile view (excludes username)
- [ ] Delete account view
- [ ] Follow / Unfollow toggle
- [ ] User search (by username or name)
- [ ] Templates: signup, login, profile, edit, search results

### Phase 3: Photo Component
- [ ] `Photo`, `Like`, `Comment` models + migrations
- [ ] `compress_photo()` utility in `photos/utils.py`
- [ ] `photo_upload_path()` callable for user-specific folder structure
- [ ] Upload photo view (with 2 MB validation + compression)
- [ ] Photo detail view (with likes + comments)
- [ ] Delete photo (own photos only)
- [ ] Like/unlike AJAX endpoint (+ creates `photo_like` notification)
- [ ] Add comment AJAX endpoint (+ creates `photo_comment` notification)
- [ ] Templates: upload, detail

### Phase 4: Newsfeed Component
- [ ] Newsfeed query (followed users' posts + community posts)
- [ ] Paginated feed view
- [ ] Feed template with photo cards (user avatar, photo, caption, like/comment counts)
- [ ] Inline like/comment interactions

### Phase 5: Community Component
- [ ] `Community`, `CommunityMembership` models + migrations
- [ ] Create community view (creator auto-added as member)
- [ ] Community detail view (photo grid, member list)
- [ ] Invite member (creates pending membership + `community_invite` notification)
- [ ] Accept/reject invitation
- [ ] Upload photo to community
- [ ] Templates: list, create, detail

### Phase 6: Notifications Component (global)
- [ ] `Notification` model + migrations in `notifications` app
- [ ] Context processor for unread notification count (navbar badge)
- [ ] Notification list view (paginated, shows all types)
- [ ] Mark single notification as read (AJAX)
- [ ] Mark all as read (AJAX)
- [ ] Templates: notification list
- [ ] Wire notification creation into: `toggle_like`, `add_comment`, `invite_member`

### Phase 7: UI Polish
- [ ] Responsive testing and fixes
- [ ] Micro-animations (fade-in feed items, button hover effects, transitions)
- [ ] Glassmorphism cards, gradients
- [ ] Mobile hamburger menu
- [ ] Empty states (no posts, no followers, no communities)
- [ ] Error pages (404, 500)

### Phase 8: Final Testing & Cleanup
- [ ] End-to-end walkthrough of all features
- [ ] Edge cases: self-follow prevention, duplicate likes, empty feeds, self-notification prevention
- [ ] Docker: verify `docker-compose up` brings up working app + db
- [ ] Code cleanup: remove dead code, verify naming conventions
- [ ] README with setup instructions (includes Docker instructions)

---

## Verification Plan

### Automated
- Run Django's `check` command: `python manage.py check`
- Run migrations: `python manage.py migrate` (confirm no errors)
- Run development server: `python manage.py runserver`

### Manual
- Walk through every user flow in the browser:
  - Signup → Login → Edit profile → Upload photo → View feed → Like/Comment → Search user → Follow → View their profile → Create community → Invite member → Accept invite → Upload community photo → Verify feed shows community posts → Delete photo → Delete account
- Test on mobile viewport (Chrome DevTools)
- Verify unique username constraint works (duplicate signup attempt)
- Verify follow/unfollow toggle, like/unlike toggle
- Verify notifications appear for: community invite, photo like, photo comment
- Verify notification bell badge updates in navbar
- Verify mark-as-read and mark-all-as-read work
- Verify photo compression: upload a >2MB image, confirm it's compressed and stored correctly
- Verify `docker-compose up` runs the full stack

---

## Deployment Strategy: Vercel

### Architecture Additions
Vercel is a serverless environment, meaning local file storage is ephemeral and databases are not hosted on the platform.

### Vercel Configuration
- `vercel.json` controls the build and routing. It specifies the `@vercel/python` builder for `wsgi.py` and a `@vercel/static-build` builder for static files (handled by `build.sh`).
- `build.sh` runs `pip install`, `collectstatic`, and `migrate` during the Vercel build step.
- `wsgi.py` exposes the `app` variable (which Vercel looks for natively).

### Media Storage
- If `AWS_STORAGE_BUCKET_NAME` is provided in environment variables, the system uses `django-storages` with `boto3` to offload user uploads to AWS S3. Otherwise, it falls back to the local `media/` folder (useful for local development, but volatile on Vercel).
