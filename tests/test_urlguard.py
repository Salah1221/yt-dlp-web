"""Tests for the URL guard. No test opens a real connection."""

from __future__ import annotations

import socket
import threading

import pytest

from app import urlguard

BLOCKED_TEXTS = [
    "127.0.0.1",
    "::1",
    "10.0.0.5",
    "172.16.0.1",
    "192.168.1.1",
    "169.254.169.254",
    "0.0.0.0",
    "224.0.0.1",
    "fc00::1",
    "fe80::1",
    "::ffff:127.0.0.1",
    "not-an-address",
]

PUBLIC_TEXTS = ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"]


def fake_answer(*addresses: str):
    """Return a stand-in for socket.getaddrinfo with a fixed answer."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
             (address, port))
            for address in addresses
        ]
    return fake_getaddrinfo


def fake_failure(host, port, *args, **kwargs):
    """Stand in for a resolver that cannot answer."""
    raise socket.gaierror("no answer")


@pytest.fixture()
def calls(monkeypatch):
    """Put the guard over a fake original, and undo it after the test.

    monkeypatch restores socket.create_connection and the two module
    flags, so the rest of the suite sees the process as it was.
    """
    seen: list = []

    def original(address, *args, **kwargs):
        seen.append(address)
        return "connected"

    monkeypatch.setattr(socket, "create_connection", original)
    monkeypatch.setattr(urlguard, "_installed", False)
    monkeypatch.setattr(urlguard, "_original_create_connection", None)
    urlguard.install()
    return seen


@pytest.mark.parametrize("text", BLOCKED_TEXTS)
def test_is_blocked_address_returns_true_for_a_blocked_text(text):
    assert urlguard.is_blocked_address(text) is True


@pytest.mark.parametrize("text", PUBLIC_TEXTS)
def test_is_blocked_address_returns_false_for_a_public_address(text):
    assert urlguard.is_blocked_address(text) is False


def test_is_blocked_address_reads_the_ipv4_inside_a_mapped_address():
    assert urlguard.is_blocked_address("::ffff:127.0.0.1") is True
    assert urlguard.is_blocked_address("::ffff:10.0.0.5") is True
    assert urlguard.is_blocked_address("::ffff:8.8.8.8") is False


def test_is_blocked_address_returns_true_for_text_that_is_not_an_address():
    assert urlguard.is_blocked_address("not-an-address") is True
    assert urlguard.is_blocked_address("") is True


def test_check_url_rejects_the_file_scheme():
    with pytest.raises(urlguard.UnsafeUrl) as error:
        urlguard.check_url("file:///etc/passwd")
    assert "file" in str(error.value)


def test_check_url_rejects_the_ftp_scheme():
    with pytest.raises(urlguard.UnsafeUrl) as error:
        urlguard.check_url("ftp://example.com/x")
    assert "ftp" in str(error.value)


def test_check_url_rejects_a_url_with_no_host():
    with pytest.raises(urlguard.UnsafeUrl):
        urlguard.check_url("http:///only/a/path")


def test_check_url_rejects_a_private_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", fake_answer("10.0.0.5"))
    with pytest.raises(urlguard.UnsafeUrl):
        urlguard.check_url("http://example.com/x")


def test_check_url_rejects_the_metadata_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", fake_answer("169.254.169.254"))
    with pytest.raises(urlguard.UnsafeUrl):
        urlguard.check_url("http://example.com/latest/meta-data/")


def test_check_url_rejects_a_public_address_beside_a_private_one(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        fake_answer("93.184.216.34", "127.0.0.1"))
    with pytest.raises(urlguard.UnsafeUrl):
        urlguard.check_url("https://example.com/x")


def test_check_url_accepts_only_public_addresses(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        fake_answer("93.184.216.34", "8.8.8.8"))
    assert urlguard.check_url("https://example.com/x") is None


def test_check_url_rejects_a_name_that_does_not_resolve(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", fake_failure)
    with pytest.raises(urlguard.UnsafeUrl) as error:
        urlguard.check_url("http://example.com/x")
    assert "resolve" in str(error.value)


def test_check_url_with_allow_private_accepts_the_loopback_address():
    assert urlguard.check_url("http://127.0.0.1:8000/x",
                              allow_private=True) is None


def test_the_message_of_a_refusal_hides_the_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", fake_answer("169.254.169.254"))
    with pytest.raises(urlguard.UnsafeUrl) as error:
        urlguard.check_url("http://example.com/x")
    assert "169.254.169.254" not in str(error.value)


def test_install_wraps_the_socket_function_one_time_only(calls):
    first = socket.create_connection
    urlguard.install()
    assert socket.create_connection is first
    urlguard.install()
    assert socket.create_connection is first


def test_create_connection_works_as_before_outside_the_guard(calls):
    assert socket.create_connection(("127.0.0.1", 80)) == "connected"
    assert calls == [("127.0.0.1", 80)]


def test_the_guard_rejects_a_blocked_address(calls):
    with urlguard.guarded():
        with pytest.raises(urlguard.UnsafeUrl):
            socket.create_connection(("169.254.169.254", 80))
    assert calls == []


def test_the_guard_accepts_a_public_address(calls):
    with urlguard.guarded():
        assert socket.create_connection(("93.184.216.34", 443)) == "connected"
    assert calls == [("93.184.216.34", 443)]


def test_the_guard_reads_the_addresses_of_a_host_name(calls, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        fake_answer("93.184.216.34", "10.0.0.5"))
    with urlguard.guarded():
        with pytest.raises(urlguard.UnsafeUrl):
            socket.create_connection(("example.com", 80))
    assert calls == []


def test_the_guard_with_allow_private_accepts_a_blocked_address(calls):
    with urlguard.guarded(allow_private=True):
        assert socket.create_connection(("127.0.0.1", 8000)) == "connected"
    assert calls == [("127.0.0.1", 8000)]


def test_the_flag_is_off_after_the_guard_block_ends(calls):
    with urlguard.guarded():
        pass
    assert socket.create_connection(("127.0.0.1", 80)) == "connected"


def test_the_flag_is_off_after_the_guard_block_raises(calls):
    with pytest.raises(RuntimeError):
        with urlguard.guarded():
            raise RuntimeError("something failed")
    assert socket.create_connection(("127.0.0.1", 80)) == "connected"


def test_a_nested_guard_block_restores_the_outer_value(calls):
    with urlguard.guarded():
        with urlguard.guarded(allow_private=True):
            assert socket.create_connection(("127.0.0.1", 80)) == "connected"
        with pytest.raises(urlguard.UnsafeUrl):
            socket.create_connection(("127.0.0.1", 80))
    assert calls == [("127.0.0.1", 80)]


def test_a_second_thread_stays_free_while_this_thread_is_guarded(calls):
    """The flag is per thread, so another thread connects as before."""
    result: dict = {}
    done = threading.Event()

    def worker():
        try:
            result["value"] = socket.create_connection(("127.0.0.1", 80))
        except Exception as error:
            result["error"] = error
        finally:
            done.set()

    thread = threading.Thread(target=worker)
    with urlguard.guarded():
        thread.start()
        assert done.wait(timeout=5.0)
        with pytest.raises(urlguard.UnsafeUrl):
            socket.create_connection(("127.0.0.1", 80))
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert result.get("value") == "connected"
    assert "error" not in result
