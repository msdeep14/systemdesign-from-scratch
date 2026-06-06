# Implementation Plan: Hourly Logging Setup

## Goal Description
The objective is to introduce a comprehensive logging system into the BSES application to aid in debugging. The system will capture both success and error scenarios. Logs will be written to a `logs` directory, and log files will be rotated on an hourly basis. The `logs` directory and its contents will not be tracked in git.

## Proposed Changes

### `bses/settings.py`
- Import `os` and `logging.handlers`.
- Add a Django `LOGGING` dictionary.
- Configure a `TimedRotatingFileHandler` with `when='H'` (hours) and `interval=1`.
- The handler will write to `logs/bses.log` (which rotates hourly to `bses.log.YYYY-MM-DD_HH`).
- Configure a custom logger named `'bses'` for application-level logging.

### Root Directory
- Create the `logs` directory to store log files locally.
- Add `logs/` to `.gitignore` to ensure it is not tracked in git.

### Views Updates
I will inject standard `import logging; logger = logging.getLogger('bses')` into all app `views.py` files to log critical paths (success and errors):

#### [MODIFY] `users/views.py`
- Log successful user registration, login, logout, profile updates, and follow/unfollow actions.
- Log error scenarios (e.g., invalid forms during registration).

#### [MODIFY] `photos/views.py`
- Log successful photo uploads, deletions, likes, and comments.
- Log errors (e.g., invalid photo uploads, missing files).

#### [MODIFY] `communities/views.py`
- Log community creation, successful joins, photo uploads to communities, and member invitations.
- Log any form validation errors or permission denials.

#### [MODIFY] `notifications/views.py`
- Log when notifications are marked as read.
