"""Stop server-side request forgery in a URL that a user sends.

The module has two layers.

The first layer is check_url. It reads the URL, resolves the host name,
and refuses an address that belongs to the machine or to the local
network. Call it when the request arrives.

The second layer is install and guarded. A check at the front door is not
enough. A redirect can point at a private address after the check passed.
A DNS answer can also change between the check and the connection. That
second case is the time of check to time of use problem. So install wraps
socket.create_connection, and guarded turns the wrapper on for the
current thread while yt-dlp runs.

The limitation, in plain words: the wrapper works because the default
network code of yt-dlp goes through Python sockets. An HTTP backend that
C code implements, such as curl_cffi, opens its sockets inside the C
library. Such a backend never calls socket.create_connection, so it goes
past the wrapper and past this whole module. Do not install curl_cffi in
this application.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse

# yt-dlp fetches media over HTTP only. Every other scheme, such as file or
# ftp, gives an attacker a way to read something that is not media.
ALLOWED_SCHEMES = ("http", "https")

DEFAULT_PORTS = {"http": 80, "https": 443}

# The message that the user sees. It never names the address, because the
# address tells the attacker what the internal network looks like.
BLOCKED_MESSAGE = "this address is not allowed"
UNRESOLVED_MESSAGE = "the name of the host could not be resolved"

# The flag lives in thread local storage. The application makes its own
# outbound connections in other threads, and those must stay free. Only
# the thread that runs a download turns the flag on.
_state = threading.local()

# install must wrap one time only. A second wrap would call the first
# wrapper, and a later uninstall could put the wrapper back in place.
_installed = False
_original_create_connection = None


class UnsafeUrl(Exception):
    """Raised when a URL or an address is not allowed."""


def is_blocked_address(ip_text: str) -> bool:
    """Return True when the address text is not safe to connect to."""
    try:
        address = ipaddress.ip_address(ip_text)
    except ValueError:
        # Text that is not an address must never count as safe. A caller
        # that cannot read the answer must still get a refusal.
        return True

    # An IPv4-mapped IPv6 address, such as ::ffff:127.0.0.1, holds an IPv4
    # address inside it. The operating system connects to that inner IPv4
    # address, so the test must run on the inner address. This form is a
    # common way to walk past a filter that only reads the outer address.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped

    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _resolve(host: str, port: int | None) -> list[str]:
    """Return every address of the host. Raise UnsafeUrl on a failure."""
    try:
        results = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError, ValueError):
        raise UnsafeUrl(UNRESOLVED_MESSAGE) from None
    addresses = [entry[4][0] for entry in results]
    if not addresses:
        # An empty answer tells us nothing, so treat it as a failure.
        raise UnsafeUrl(UNRESOLVED_MESSAGE)
    return addresses


def _reject_blocked(addresses: list[str]) -> None:
    """Raise UnsafeUrl when one address of the list is blocked.

    Every address must pass. One name can resolve to a public address and
    to a private address at the same time. If only the first address is
    tested, the connection can still land on the private one.
    """
    for ip_text in addresses:
        if is_blocked_address(ip_text):
            raise UnsafeUrl(BLOCKED_MESSAGE)


def check_url(url: str, allow_private: bool = False) -> None:
    """Check the URL before the download starts. Raise UnsafeUrl if bad.

    Set allow_private to True for a home machine. There a download from a
    disk on the local network is a normal thing to do.
    """
    if allow_private:
        return None

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrl(f"the scheme '{scheme}' is not allowed")

    host = parsed.hostname
    if not host:
        raise UnsafeUrl("the URL has no host")

    try:
        port = parsed.port
    except ValueError:
        # A port that is not a number makes the URL invalid. Refuse it.
        raise UnsafeUrl("the URL has a bad port") from None
    if port is None:
        port = DEFAULT_PORTS[scheme]

    _reject_blocked(_resolve(host, port))
    return None


def _check_target(host: str, port: int | None) -> None:
    """Raise UnsafeUrl when the connect target is a blocked address."""
    text = str(host).strip("[]")
    try:
        ipaddress.ip_address(text)
    except ValueError:
        # The host is a name, so ask the resolver and test every answer.
        _reject_blocked(_resolve(text, port))
        return
    # The host is already an address, so no lookup is needed.
    _reject_blocked([text])


def install() -> None:
    """Wrap socket.create_connection one time. Safe to call again.

    The wrapper does nothing until a thread enters guarded. Call this one
    time when the application starts.
    """
    global _installed, _original_create_connection
    if _installed:
        return

    original = socket.create_connection

    def create_connection(address, *args, **kwargs):
        if getattr(_state, "active", False) and not getattr(
                _state, "allow_private", False):
            host = address[0]
            port = address[1] if len(address) > 1 else None
            _check_target(host, port)
        return original(address, *args, **kwargs)

    create_connection.__name__ = "create_connection"
    create_connection.__doc__ = original.__doc__
    _original_create_connection = original
    socket.create_connection = create_connection
    _installed = True


@contextmanager
def guarded(allow_private: bool = False) -> Iterator[None]:
    """Turn the connection guard on for this thread only.

    The guard has an effect only after a call to install. On exit the old
    value comes back, so a nested block leaves the outer block as it was.
    An exception inside the block restores the old value too.
    """
    previous_active = getattr(_state, "active", False)
    previous_allow = getattr(_state, "allow_private", False)
    _state.active = True
    _state.allow_private = allow_private
    try:
        yield
    finally:
        _state.active = previous_active
        _state.allow_private = previous_allow
