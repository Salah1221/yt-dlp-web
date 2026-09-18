import pytest
from fastapi.testclient import TestClient

from app import jobs, main


@pytest.fixture()
def store(tmp_path):
    return jobs.JobStore(tmp_path, ttl_seconds=600)


@pytest.fixture()
def client(store, monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_WEB_TEMP_ROOT", str(tmp_path))
    app = main.create_app(store=store)
    with TestClient(app) as test_client:
        yield test_client


def test_the_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_probe_returns_the_video_data(client, media_url):
    response = client.post("/api/probe", json={"url": media_url})
    assert response.status_code == 200
    body = response.json()
    assert body["title"]
    assert body["formats"]


def test_probe_reports_a_bad_url_as_400(client):
    response = client.post("/api/probe",
                           json={"url": "http://127.0.0.1:1/missing.mp4"})
    assert response.status_code == 400
    assert response.json()["detail"]


def test_start_job_rejects_an_unknown_mode(client):
    response = client.post("/api/jobs",
                           json={"url": "http://x/y.mp4", "mode": "gif"})
    assert response.status_code == 400


def test_start_job_rejects_format_mode_without_a_format_id(client):
    response = client.post("/api/jobs",
                           json={"url": "http://x/y.mp4", "mode": "format"})
    assert response.status_code == 400


def test_start_job_returns_a_job_id(client, media_url):
    response = client.post("/api/jobs",
                           json={"url": media_url, "mode": "audio"})
    assert response.status_code == 200
    assert len(response.json()["job_id"]) == 32


def test_job_state_is_404_for_an_unknown_id(client):
    assert client.get("/api/jobs/" + "0" * 32).status_code == 404


def test_job_state_hides_the_server_path(client, store):
    job = store.create("http://x/y.mp4", "audio")
    store.update(job.id, file_path="C:/secret/song.mp3")
    body = client.get(f"/api/jobs/{job.id}").json()
    assert body["id"] == job.id
    assert "file_path" not in body


def test_cancel_marks_the_job_and_deletes_a_finished_folder(client, store, tmp_path):
    job = store.create("http://x/y.mp4", "audio")
    store.update(job.id, state=jobs.READY, file_path="x")
    assert client.delete(f"/api/jobs/{job.id}").status_code == 200
    assert store.get(job.id) is None
    assert not (tmp_path / job.id).exists()


def test_cancel_is_404_for_an_unknown_id(client):
    assert client.delete("/api/jobs/" + "0" * 32).status_code == 404


def test_content_disposition_carries_both_name_forms():
    header = main.content_disposition("Café Song.mp3")
    assert header.startswith("attachment; ")
    assert 'filename="' in header
    assert "filename*=UTF-8''Caf%C3%A9%20Song.mp3" in header


def _ready_job(store, tmp_path, name="song.mp3", data=b"audio-bytes"):
    job = store.create("http://x/y.mp4", "audio")
    path = tmp_path / job.id / name
    path.write_bytes(data)
    store.update(job.id, state=jobs.READY, filename=name,
                 file_path=str(path), percent=100.0)
    return job


def test_file_route_is_404_for_an_unknown_id(client):
    assert client.get("/api/jobs/" + "0" * 32 + "/file").status_code == 404


def test_file_route_is_409_while_the_job_runs(client, store):
    job = store.create("http://x/y.mp4", "audio")
    store.update(job.id, state=jobs.DOWNLOADING)
    assert client.get(f"/api/jobs/{job.id}/file").status_code == 409


def test_file_route_is_410_when_the_file_is_gone(client, store, tmp_path):
    job = _ready_job(store, tmp_path)
    (tmp_path / job.id / "song.mp3").unlink()
    assert client.get(f"/api/jobs/{job.id}/file").status_code == 410


def test_file_route_sends_the_bytes_as_an_attachment(client, store, tmp_path):
    job = _ready_job(store, tmp_path)
    response = client.get(f"/api/jobs/{job.id}/file")
    assert response.status_code == 200
    assert response.content == b"audio-bytes"
    assert response.headers["content-disposition"].startswith("attachment; ")
    assert "song.mp3" in response.headers["content-disposition"]


def test_file_route_deletes_the_folder_after_it_sends(client, store, tmp_path):
    job = _ready_job(store, tmp_path)
    client.get(f"/api/jobs/{job.id}/file")
    assert not (tmp_path / job.id).exists()
    assert store.get(job.id) is None


def test_a_second_download_gets_404(client, store, tmp_path):
    job = _ready_job(store, tmp_path)
    client.get(f"/api/jobs/{job.id}/file")
    assert client.get(f"/api/jobs/{job.id}/file").status_code == 404
