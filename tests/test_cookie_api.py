"""The routes behind the settings panel."""

import pytest
from fastapi.testclient import TestClient

from app import config, jobs, main

LINE = ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tabc123"


@pytest.fixture()
def store(tmp_path):
    return jobs.JobStore(tmp_path, ttl_seconds=600)


@pytest.fixture()
def client(store, monkeypatch, tmp_path):
    monkeypatch.setenv(config.TEMP_ROOT_ENV, str(tmp_path))
    monkeypatch.delenv(config.COOKIE_FILE_ENV, raising=False)
    with TestClient(main.create_app(store=store)) as test_client:
        yield test_client


def test_the_status_starts_empty(client):
    body = client.get("/api/cookies").json()
    assert body["source"] == "none"
    assert body["count"] == 0


def test_a_paste_is_saved_and_reported(client):
    body = client.put("/api/cookies", json={"text": LINE}).json()
    assert body["source"] == "pasted"
    assert body["count"] == 1
    assert client.get("/api/cookies").json()["domains"] == ["youtube.com"]


def test_a_bad_paste_is_a_400_that_says_why(client):
    response = client.put("/api/cookies", json={"text": "hello"})
    assert response.status_code == 400
    assert "cookie" in response.json()["detail"]


def test_removing_empties_the_status(client):
    client.put("/api/cookies", json={"text": LINE})
    assert client.delete("/api/cookies").json()["source"] == "none"


def test_no_route_sends_the_cookies_back(client):
    client.put("/api/cookies", json={"text": LINE})
    for response in (client.get("/api/cookies"),
                     client.put("/api/cookies", json={"text": LINE}),
                     client.delete("/api/cookies")):
        assert "abc123" not in response.text


def test_the_login_guards_the_routes(store, monkeypatch, tmp_path):
    monkeypatch.setenv(config.TEMP_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv("YTDLP_WEB_PASSWORD", "a-long-enough-password")
    with TestClient(main.create_app(store=store)) as client:
        assert client.get("/api/cookies").status_code == 401
        assert client.put("/api/cookies", json={"text": LINE}).status_code == 401
        assert client.delete("/api/cookies").status_code == 401
        client.post("/api/login", json={"password": "a-long-enough-password"})
        assert client.get("/api/cookies").status_code == 200


def test_the_page_offers_the_settings_button(client):
    page = client.get("/").text
    assert 'id="settings-toggle"' in page
    assert 'id="cookie-text"' in page
    assert 'id="cookie-save"' in page
    # The panel is a dialog, so the page behind it goes soft.
    assert "<dialog" in page


def test_the_paste_box_is_covered_and_empties_itself(client):
    script = client.get("/static/app.js").text
    style = client.get("/static/style.css").text
    # The box reads as a password field, and nothing stays in it: Save
    # empties it, and so does closing the dialog.
    assert "-webkit-text-security" in style
    assert "backdrop-filter" in style
    assert script.count('el("cookie-text").value = ""') >= 2
