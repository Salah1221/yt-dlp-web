import threading

import pytest
from fastapi.testclient import TestClient

from app import jobs, limits, main


@pytest.fixture()
def store(tmp_path):
    return jobs.JobStore(tmp_path, ttl_seconds=600)


@pytest.fixture(autouse=True)
def local_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_WEB_TEMP_ROOT", str(tmp_path))
    monkeypatch.delenv("YTDLP_WEB_PASSWORD", raising=False)


def test_a_second_job_is_refused_when_one_slot_is_set(monkeypatch, store):
    monkeypatch.setenv("YTDLP_WEB_MAX_JOBS", "1")
    release = threading.Event()
    monkeypatch.setattr(main.downloader, "run",
                        lambda job, job_store: release.wait(timeout=5))
    body = {"url": "http://127.0.0.1:1/x.mp4", "mode": "audio"}
    try:
        with TestClient(main.create_app(store=store)) as client:
            assert client.post("/api/jobs", json=body).status_code == 200
            second = client.post("/api/jobs", json=body)
            assert second.status_code == 429
            assert "already running" in second.json()["detail"]
    finally:
        release.set()


def test_the_slot_is_free_again_after_the_job_ends(monkeypatch, store):
    monkeypatch.setenv("YTDLP_WEB_MAX_JOBS", "1")
    monkeypatch.setattr(main.downloader, "run", lambda job, job_store: None)
    body = {"url": "http://127.0.0.1:1/x.mp4", "mode": "audio"}
    with TestClient(main.create_app(store=store)) as client:
        assert client.post("/api/jobs", json=body).status_code == 200
        for _ in range(20):
            response = client.post("/api/jobs", json=body)
            if response.status_code == 200:
                break
        assert response.status_code == 200


def test_a_full_disk_refuses_the_job(monkeypatch, store):
    monkeypatch.setattr(limits, "has_room", lambda path, needed: False)
    with TestClient(main.create_app(store=store)) as client:
        response = client.post("/api/jobs", json={
            "url": "http://127.0.0.1:1/x.mp4", "mode": "audio"})
        assert response.status_code == 507
        assert "disk" in response.json()["detail"]
