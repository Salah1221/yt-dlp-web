import pytest
from fastapi.testclient import TestClient

from app import auth, jobs, main

PASSWORD = "a-long-enough-password"


@pytest.fixture()
def store(tmp_path):
    return jobs.JobStore(tmp_path, ttl_seconds=600)


@pytest.fixture(autouse=True)
def no_login_delay(monkeypatch):
    # The real delay slows a password guesser. It would also slow the tests.
    monkeypatch.setattr(main, "FAILED_LOGIN_DELAY", 0.0)


@pytest.fixture()
def open_client(store, monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_WEB_TEMP_ROOT", str(tmp_path))
    monkeypatch.delenv("YTDLP_WEB_PASSWORD", raising=False)
    with TestClient(main.create_app(store=store)) as client:
        yield client


@pytest.fixture()
def locked_client(store, monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_WEB_TEMP_ROOT", str(tmp_path))
    monkeypatch.setenv("YTDLP_WEB_PASSWORD", PASSWORD)
    with TestClient(main.create_app(store=store)) as client:
        yield client


def login(client):
    response = client.post("/api/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return response


def test_without_a_password_every_route_is_open(open_client):
    assert open_client.get("/").status_code == 200
    assert open_client.get("/api/jobs/" + "0" * 32).status_code == 404


def test_with_a_password_the_api_refuses_without_a_cookie(locked_client):
    response = locked_client.get("/api/jobs/" + "0" * 32)
    assert response.status_code == 401
    assert response.json()["detail"]


def test_with_a_password_the_page_sends_you_to_the_login(locked_client):
    response = locked_client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_the_login_page_is_reachable_without_a_cookie(locked_client):
    response = locked_client.get("/login")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_the_static_files_are_reachable_without_a_cookie(locked_client):
    assert locked_client.get("/static/style.css").status_code == 200


def test_a_wrong_password_is_refused(locked_client):
    response = locked_client.post("/api/login", json={"password": "wrong"})
    assert response.status_code == 401
    assert auth.COOKIE_NAME not in response.cookies


def test_the_right_password_sets_a_protected_cookie(locked_client):
    response = login(locked_client)
    header = response.headers["set-cookie"]
    assert auth.COOKIE_NAME in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header.replace("samesite", "SameSite")


def test_after_the_login_the_api_answers(locked_client):
    login(locked_client)
    assert locked_client.get("/api/jobs/" + "0" * 32).status_code == 404
    assert locked_client.get("/", follow_redirects=False).status_code == 200


def test_a_forged_cookie_does_not_work(locked_client):
    locked_client.cookies.set(auth.COOKIE_NAME, "9999999999.deadbeef")
    assert locked_client.get("/api/jobs/" + "0" * 32).status_code == 401


def test_logout_clears_the_cookie(locked_client):
    login(locked_client)
    assert locked_client.post("/api/logout").status_code == 200
    locked_client.cookies.clear()
    assert locked_client.get("/api/jobs/" + "0" * 32).status_code == 401


def test_too_many_wrong_passwords_are_refused(locked_client):
    seen = set()
    for _ in range(12):
        seen.add(locked_client.post("/api/login",
                                    json={"password": "wrong"}).status_code)
    assert 429 in seen


def test_the_progress_socket_refuses_without_a_cookie(locked_client, store):
    job = store.create("http://x/y.mp4", "audio")
    with pytest.raises(Exception):
        with locked_client.websocket_connect(f"/ws/{job.id}") as socket:
            socket.receive_json()


def test_the_progress_socket_answers_after_the_login(locked_client, store):
    login(locked_client)
    job = store.create("http://x/y.mp4", "audio")
    with locked_client.websocket_connect(f"/ws/{job.id}") as socket:
        assert socket.receive_json()["id"] == job.id


def test_the_page_config_reports_no_login_in_local_mode(open_client):
    assert open_client.get("/api/config").json() == {"login": False}


def test_the_page_config_reports_the_login_after_you_are_in(locked_client):
    login(locked_client)
    assert locked_client.get("/api/config").json() == {"login": True}
