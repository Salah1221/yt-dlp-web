import time

import pytest

from app import auth


PASSWORD = "a-long-enough-password"


def test_a_fresh_cookie_is_accepted():
    cookie = auth.make_cookie(PASSWORD)
    assert auth.check_cookie(cookie, PASSWORD) is True


def test_a_cookie_from_another_password_is_refused():
    cookie = auth.make_cookie(PASSWORD)
    assert auth.check_cookie(cookie, "a-different-password") is False


def test_an_expired_cookie_is_refused():
    past = time.time() - auth.SESSION_SECONDS - 10
    cookie = auth.make_cookie(PASSWORD, now=past)
    assert auth.check_cookie(cookie, PASSWORD) is False


def test_a_cookie_that_expires_later_is_accepted():
    cookie = auth.make_cookie(PASSWORD, now=time.time())
    assert auth.check_cookie(cookie, PASSWORD, now=time.time() + 60) is True


def test_a_tampered_expiry_is_refused():
    cookie = auth.make_cookie(PASSWORD)
    expiry, _, signature = cookie.rpartition(".")
    forged = f"{int(expiry) + 999999}.{signature}"
    assert auth.check_cookie(forged, PASSWORD) is False


def test_a_tampered_signature_is_refused():
    cookie = auth.make_cookie(PASSWORD)
    expiry, _, signature = cookie.rpartition(".")
    forged = expiry + "." + ("0" * len(signature))
    assert auth.check_cookie(forged, PASSWORD) is False


def test_rubbish_cookies_are_refused():
    for bad in ("", "  ", "nodot", "a.b", ".", "123.", "abc.def"):
        assert auth.check_cookie(bad, PASSWORD) is False


def test_a_cookie_survives_a_restart_because_the_key_comes_from_the_password():
    first = auth.signing_key(PASSWORD)
    second = auth.signing_key(PASSWORD)
    assert first == second


def test_changing_the_password_changes_the_key():
    assert auth.signing_key(PASSWORD) != auth.signing_key(PASSWORD + "x")


def test_the_right_password_is_accepted():
    assert auth.check_password(PASSWORD, PASSWORD) is True


def test_a_wrong_password_is_refused():
    assert auth.check_password("wrong", PASSWORD) is False
    assert auth.check_password("", PASSWORD) is False
    assert auth.check_password(PASSWORD + " ", PASSWORD) is False


def test_a_prefix_of_the_password_is_refused():
    assert auth.check_password(PASSWORD[:-1], PASSWORD) is False


def test_the_limiter_allows_attempts_below_the_limit():
    limiter = auth.LoginLimiter(limit=3, window=60)
    for _ in range(3):
        assert limiter.allow("1.2.3.4") is True
        limiter.record_failure("1.2.3.4")


def test_the_limiter_blocks_after_the_limit():
    limiter = auth.LoginLimiter(limit=3, window=60)
    for _ in range(3):
        limiter.record_failure("1.2.3.4")
    assert limiter.allow("1.2.3.4") is False


def test_the_limiter_counts_each_address_on_its_own():
    limiter = auth.LoginLimiter(limit=2, window=60)
    for _ in range(2):
        limiter.record_failure("1.2.3.4")
    assert limiter.allow("1.2.3.4") is False
    assert limiter.allow("5.6.7.8") is True


def test_the_limiter_forgets_old_failures():
    limiter = auth.LoginLimiter(limit=2, window=60)
    old = time.monotonic() - 120
    limiter.record_failure("1.2.3.4", now=old)
    limiter.record_failure("1.2.3.4", now=old)
    assert limiter.allow("1.2.3.4") is True


def test_a_success_clears_the_failures():
    limiter = auth.LoginLimiter(limit=2, window=60)
    limiter.record_failure("1.2.3.4")
    limiter.record_success("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    assert limiter.allow("1.2.3.4") is True
