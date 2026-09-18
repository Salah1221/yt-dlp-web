import pytest
from fastapi.testclient import TestClient

from app import config, downloader, jobs, main, urlguard


@pytest.fixture()
def store(tmp_path):
    return jobs.JobStore(tmp_path, ttl_seconds=600)


@pytest.fixture()
def public_mode(monkeypatch):
    """Act as if the server binds to a public address."""
    monkeypatch.setattr(config, "block_private_addresses", lambda: True)


def test_probe_refuses_a_private_url_in_public_mode(public_mode):
    with pytest.raises(urlguard.UnsafeUrl):
        downloader.probe("http://127.0.0.1:8000/x.mp4")


def test_probe_refuses_a_bad_scheme_in_public_mode(public_mode):
    with pytest.raises(urlguard.UnsafeUrl):
        downloader.probe("file:///etc/passwd")


def test_probe_allows_a_private_url_in_local_mode(monkeypatch, media_url):
    monkeypatch.setattr(config, "block_private_addresses", lambda: False)
    assert downloader.probe(media_url)["title"]


def test_run_records_the_guard_error_in_public_mode(public_mode, store, tmp_path):
    job = store.create("http://169.254.169.254/latest/meta-data/", "audio")
    downloader.run(job, store)
    done = store.get(job.id)
    assert done.state == jobs.ERROR
    assert "not allowed" in done.error
    assert not (tmp_path / job.id).exists()


def test_the_guard_error_does_not_leak_the_address(public_mode, store):
    job = store.create("http://192.168.1.50/private.mp4", "audio")
    downloader.run(job, store)
    assert "192.168" not in store.get(job.id).error


def test_the_probe_route_reports_a_blocked_url_as_400(public_mode, store,
                                                      monkeypatch, tmp_path):
    # Public mode needs a password, or the application refuses to start.
    monkeypatch.setenv("YTDLP_WEB_TEMP_ROOT", str(tmp_path))
    monkeypatch.setenv("YTDLP_WEB_PASSWORD", "a-long-enough-password")
    with TestClient(main.create_app(store=store)) as client:
        client.post("/api/login", json={"password": "a-long-enough-password"})
        response = client.post("/api/probe",
                               json={"url": "http://10.0.0.1/x.mp4"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]


def test_public_mode_without_a_password_refuses_to_start(public_mode, store,
                                                         monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_WEB_TEMP_ROOT", str(tmp_path))
    monkeypatch.delenv("YTDLP_WEB_PASSWORD", raising=False)
    with pytest.raises(RuntimeError) as caught:
        with TestClient(main.create_app(store=store)):
            pass
    assert "YTDLP_WEB_PASSWORD" in str(caught.value)


def test_the_size_limit_reaches_the_yt_dlp_options(tmp_path, monkeypatch):
    monkeypatch.setenv("YTDLP_WEB_MAX_FILESIZE", "2147483648")
    opts = downloader.build_opts("video", str(tmp_path),
                                 max_filesize=config.max_filesize())
    assert opts["max_filesize"] == 2147483648


def test_no_size_limit_leaves_the_option_out(tmp_path):
    opts = downloader.build_opts("video", str(tmp_path), max_filesize=None)
    assert "max_filesize" not in opts
