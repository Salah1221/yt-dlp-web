from pathlib import Path

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
