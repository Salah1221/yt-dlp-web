import pytest
from fastapi.testclient import TestClient

from app import jobs, main


@pytest.fixture()
def store(tmp_path):
    return jobs.JobStore(tmp_path, ttl_seconds=600)


@pytest.fixture()
def client(store, monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_WEB_TEMP_ROOT", str(tmp_path))
    with TestClient(main.create_app(store=store)) as test_client:
        yield test_client


def test_the_socket_sends_the_present_state_first(client, store):
    job = store.create("http://x/y.mp4", "audio")
    with client.websocket_connect(f"/ws/{job.id}") as socket:
        first = socket.receive_json()
    assert first["id"] == job.id
    assert first["state"] == jobs.QUEUED


def test_the_socket_sends_every_update_and_then_closes(client, store):
    job = store.create("http://x/y.mp4", "audio")
    with client.websocket_connect(f"/ws/{job.id}") as socket:
        socket.receive_json()
        store.update(job.id, state=jobs.DOWNLOADING, percent=50.0)
        store.publish(job.id, store.get(job.id).public())
        store.update(job.id, state=jobs.READY, percent=100.0,
                     filename="song.mp3")
        store.publish(job.id, store.get(job.id).public())

        second = socket.receive_json()
        third = socket.receive_json()

    assert second["state"] == jobs.DOWNLOADING
    assert second["percent"] == 50.0
    assert third["state"] == jobs.READY
    assert third["filename"] == "song.mp3"


def test_the_socket_never_sends_a_server_path(client, store):
    job = store.create("http://x/y.mp4", "audio")
    store.update(job.id, file_path="C:/secret/song.mp3")
    with client.websocket_connect(f"/ws/{job.id}") as socket:
        payload = socket.receive_json()
    assert "file_path" not in payload
    assert "workdir" not in payload


def test_an_unknown_job_closes_the_socket(client):
    with client.websocket_connect("/ws/" + "0" * 32) as socket:
        with pytest.raises(Exception):
            socket.receive_json()
