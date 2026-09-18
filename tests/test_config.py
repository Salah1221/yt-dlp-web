from pathlib import Path

import pytest

from app import config


def test_server_binds_to_loopback_only():
    assert config.HOST == "127.0.0.1"
    assert config.PORT == 8000


def test_ttl_and_interval_are_positive():
    assert config.JOB_TTL_SECONDS > 0
    assert config.CLEANUP_INTERVAL_SECONDS > 0
    assert config.CLEANUP_INTERVAL_SECONDS < config.JOB_TTL_SECONDS


def test_temp_root_is_a_path_and_ends_with_the_app_folder():
    root = config.temp_root()
    assert isinstance(root, Path)
    assert root.name == "ytdlp-web"


def test_temp_root_honours_the_environment_override(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_WEB_TEMP_ROOT", str(tmp_path))
    assert config.temp_root() == tmp_path


def test_no_password_by_default(monkeypatch):
    monkeypatch.delenv("YTDLP_WEB_PASSWORD", raising=False)
    assert config.password() is None


def test_an_empty_password_counts_as_no_password(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_PASSWORD", "   ")
    assert config.password() is None


def test_the_password_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_PASSWORD", "secret")
    assert config.password() == "secret"
    assert config.require_login() is True


def test_the_host_and_port_have_safe_defaults(monkeypatch):
    monkeypatch.delenv("YTDLP_WEB_HOST", raising=False)
    monkeypatch.delenv("YTDLP_WEB_PORT", raising=False)
    assert config.host() == "127.0.0.1"
    assert config.port() == 8000


def test_the_host_and_port_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("YTDLP_WEB_PORT", "9001")
    assert config.host() == "0.0.0.0"
    assert config.port() == 9001


def test_loopback_hosts_are_recognised():
    for good in ("127.0.0.1", "::1", "localhost", "127.0.0.5"):
        assert config.is_loopback_host(good) is True
    for bad in ("0.0.0.0", "192.168.1.10", "example.com", "::"):
        assert config.is_loopback_host(bad) is False


def test_the_guard_is_off_only_for_a_private_machine(monkeypatch):
    monkeypatch.delenv("YTDLP_WEB_PASSWORD", raising=False)
    monkeypatch.setenv("YTDLP_WEB_HOST", "127.0.0.1")
    assert config.block_private_addresses() is False


def test_the_guard_is_on_for_a_public_binding(monkeypatch):
    monkeypatch.delenv("YTDLP_WEB_PASSWORD", raising=False)
    monkeypatch.setenv("YTDLP_WEB_HOST", "0.0.0.0")
    assert config.block_private_addresses() is True


def test_the_guard_is_on_behind_a_reverse_proxy(monkeypatch):
    """The proxy case: a loopback binding that the internet still reaches.

    The server binds to 127.0.0.1 because nginx sits in front of it. The
    binding therefore looks local, but anybody can send it a URL. The
    password is what says this server is not private.
    """
    monkeypatch.setenv("YTDLP_WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("YTDLP_WEB_PASSWORD", "a-long-enough-password")
    assert config.block_private_addresses() is True


def test_startup_allows_loopback_without_a_password(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_HOST", "127.0.0.1")
    monkeypatch.delenv("YTDLP_WEB_PASSWORD", raising=False)
    config.check_startup()


def test_startup_refuses_a_public_host_without_a_password(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_HOST", "0.0.0.0")
    monkeypatch.delenv("YTDLP_WEB_PASSWORD", raising=False)
    with pytest.raises(RuntimeError) as caught:
        config.check_startup()
    assert "YTDLP_WEB_PASSWORD" in str(caught.value)


def test_startup_allows_a_public_host_with_a_password(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("YTDLP_WEB_PASSWORD", "secret")
    config.check_startup()


def test_the_limits_have_defaults(monkeypatch):
    for name in ("YTDLP_WEB_MAX_FILESIZE", "YTDLP_WEB_MAX_JOBS", "YTDLP_WEB_TTL"):
        monkeypatch.delenv(name, raising=False)
    assert config.max_filesize() is None
    assert config.max_jobs() >= 1
    assert config.job_ttl() == config.JOB_TTL_SECONDS


def test_the_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_MAX_FILESIZE", "2147483648")
    monkeypatch.setenv("YTDLP_WEB_MAX_JOBS", "1")
    monkeypatch.setenv("YTDLP_WEB_TTL", "600")
    assert config.max_filesize() == 2147483648
    assert config.max_jobs() == 1
    assert config.job_ttl() == 600


def test_a_zero_size_limit_means_no_limit(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_MAX_FILESIZE", "0")
    assert config.max_filesize() is None


def test_a_bad_number_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_MAX_JOBS", "plenty")
    assert config.max_jobs() >= 1


def test_the_free_space_needed_is_three_times_the_size_limit(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_MAX_FILESIZE", "1000")
    assert config.min_free_bytes() == 3000


def test_no_size_limit_means_no_free_space_rule(monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_MAX_FILESIZE", "0")
    assert config.min_free_bytes() == 0
