import threading
import time

_local = threading.local()

FORCE_PRIMARY_COOKIE = "force_primary"
FORCE_PRIMARY_TTL_SECONDS = 5
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

__all__ = ["ReadYourWritesMiddleware", "is_primary_forced"]


def is_primary_forced() -> bool:
    """
    Returns True if the current thread should route reads to the primary.
    Called by the database router.
    """
    expires_at = getattr(_local, "force_primary_until", 0)
    return time.time() < expires_at


class ReadYourWritesMiddleware:
    """
    Middleware that ensures read-your-writes consistency when using read replicas.

    On a write request (POST, PUT, PATCH, DELETE):
      1. Sets a thread-local flag so the DB router sends in-request reads to primary.
      2. Sets a short-lived cookie on the response so the next request from this
         client also routes reads to primary (giving replication time to catch up).

    On a read request with the cookie present:
      1. Sets the thread-local flag so the DB router routes reads to primary for
         the duration of this request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_write = request.method in WRITE_METHODS

        if is_write or request.COOKIES.get(FORCE_PRIMARY_COOKIE):
            self._set_force_primary_in_thread()

        try:
            response = self.get_response(request)

            if is_write:
                response.set_cookie(
                    FORCE_PRIMARY_COOKIE,
                    "1",
                    max_age=FORCE_PRIMARY_TTL_SECONDS,
                    httponly=True,
                    samesite="Lax",
                )
            return response
        finally:
            self._clear_force_primary_in_thread()

    def _set_force_primary_in_thread(self):
        _local.force_primary_until = time.time() + FORCE_PRIMARY_TTL_SECONDS

    def _clear_force_primary_in_thread(self):
        _local.force_primary_until = 0
