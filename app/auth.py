"""The login: one password, and a signed cookie.

There is no session table. The cookie carries its own expiry time and a
signature over that time. The server checks the signature on each request.
A restart therefore does not log anybody out.

The signing key comes from the password itself. This avoids a second
setting to manage, and it has a useful effect: a new password makes every
cookie that was issued with the old one invalid at once.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque

COOKIE_NAME = "ytdlp_session"

# 30 days. A phone should not have to log in every week.
SESSION_SECONDS = 30 * 24 * 60 * 60

_KEY_LABEL = b"ytdlp-web-session"


def signing_key(password: str) -> bytes:
    """Derive the cookie signing key from the password."""
    return hmac.new(password.encode("utf-8"), _KEY_LABEL, hashlib.sha256).digest()


def _signature(payload: str, password: str) -> str:
    return hmac.new(signing_key(password), payload.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def make_cookie(password: str, now: float | None = None) -> str:
    """Return a cookie value of the form '<expiry>.<signature>'."""
    moment = time.time() if now is None else now
    payload = str(int(moment + SESSION_SECONDS))
    return f"{payload}.{_signature(payload, password)}"


def check_cookie(value: str | None, password: str,
                 now: float | None = None) -> bool:
    """Return True when the cookie is genuine and has not expired."""
    if not value or "." not in value:
        return False
    payload, _, signature = value.rpartition(".")
    # Check the signature before the expiry. An unsigned value must never
    # reach the number parsing, whatever it holds.
    if not hmac.compare_digest(signature, _signature(payload, password)):
        return False
    try:
        expiry = int(payload)
    except ValueError:
        return False
    moment = time.time() if now is None else now
    return expiry > moment


def check_password(sent: str | None, password: str | None) -> bool:
    """Compare two passwords in constant time.

    A plain '==' stops at the first wrong character. The time it takes
    therefore tells an attacker how much of the password is right, one
    character at a time. compare_digest always takes the same time.
    """
    if not password or sent is None:
        return False
    return hmac.compare_digest(sent.encode("utf-8"), password.encode("utf-8"))


class LoginLimiter:
    """Count the failed logins of each address inside a moving window."""

    def __init__(self, limit: int = 10, window: int = 3600) -> None:
        self._limit = limit
        self._window = window
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, moment: float) -> deque[float]:
        history = self._failures[key]
        while history and moment - history[0] > self._window:
            history.popleft()
        return history

    def allow(self, key: str, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        return len(self._prune(key, moment)) < self._limit

    def record_failure(self, key: str, now: float | None = None) -> None:
        moment = time.monotonic() if now is None else now
        self._prune(key, moment).append(moment)

    def record_success(self, key: str, now: float | None = None) -> None:
        self._failures.pop(key, None)
