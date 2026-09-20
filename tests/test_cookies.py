"""The cookie settings that answer the robot check of a video site."""

import pytest
from yt_dlp.utils import DownloadError

from app import cleanup, config, downloader

BOT_MESSAGE = ("ERROR: [youtube] NX45ctOJnpg: Sign in to confirm you’re "
               "not a bot. Use --cookies-from-browser or --cookies for the "
               "authentication.")


@pytest.fixture()
def cookie_jar(tmp_path, monkeypatch):
    """Write a cookies.txt and name it in the environment."""
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv(config.COOKIE_FILE_ENV, str(path))
    monkeypatch.setenv(config.TEMP_ROOT_ENV, str(tmp_path / "work"))
    return path


def test_no_setting_means_no_cookie_option():
    with downloader.cookie_opts() as opts:
        assert opts == {}


def test_the_cookie_file_reaches_yt_dlp(cookie_jar):
    with downloader.cookie_opts() as opts:
        assert "cookiefile" in opts
        assert open(opts["cookiefile"]).read() == cookie_jar.read_text()


def test_yt_dlp_reads_a_copy_and_never_the_operator_file(cookie_jar):
    with downloader.cookie_opts() as opts:
        copy = opts["cookiefile"]
        assert copy != str(cookie_jar)
        # yt-dlp writes the jar back when it closes. That write must land
        # on the copy, so the file the operator placed stays as it is.
        open(copy, "w").write("rewritten by yt-dlp\n")
    assert cookie_jar.read_text() == "# Netscape HTTP Cookie File\n"


def test_the_copy_is_deleted_when_the_call_ends(cookie_jar):
    import os

    with downloader.cookie_opts() as opts:
        copy = opts["cookiefile"]
    assert not os.path.exists(copy)


def test_two_calls_use_two_copies(cookie_jar):
    with downloader.cookie_opts() as first:
        with downloader.cookie_opts() as second:
            assert first["cookiefile"] != second["cookiefile"]


def test_the_browser_setting_reaches_yt_dlp(monkeypatch):
    monkeypatch.setenv(config.COOKIE_BROWSER_ENV, "firefox")
    with downloader.cookie_opts() as opts:
        assert opts["cookiesfrombrowser"] == ("firefox", None, None, None)


def test_the_browser_setting_reads_a_profile_and_a_container(monkeypatch):
    monkeypatch.setenv(config.COOKIE_BROWSER_ENV, "firefox:default::Meta")
    assert config.cookies_from_browser() == ("firefox", "default", None, "Meta")


def test_the_browser_setting_reads_a_keyring(monkeypatch):
    monkeypatch.setenv(config.COOKIE_BROWSER_ENV, "vivaldi+basictext:default")
    assert config.cookies_from_browser() == ("vivaldi", "default",
                                             "BASICTEXT", None)


def test_a_blank_browser_setting_is_no_setting(monkeypatch):
    monkeypatch.setenv(config.COOKIE_BROWSER_ENV, "  ")
    assert config.cookies_from_browser() is None


def test_the_robot_message_names_the_cookie_setting():
    message = downloader.explain(DownloadError(BOT_MESSAGE))
    assert config.COOKIE_FILE_ENV in message
    assert "--cookies-from-browser" not in message


def test_the_robot_message_changes_when_cookies_are_set(cookie_jar):
    message = downloader.explain(DownloadError(BOT_MESSAGE))
    assert "refused the cookies" in message
    assert config.COOKIE_FILE_ENV not in message


def test_every_other_error_keeps_its_own_words():
    error = DownloadError("ERROR: unable to download video data: HTTP 404")
    assert downloader.explain(error) == str(error)


def test_a_missing_cookie_file_stops_the_start(monkeypatch, tmp_path):
    monkeypatch.setenv(config.COOKIE_FILE_ENV, str(tmp_path / "absent.txt"))
    with pytest.raises(RuntimeError) as caught:
        config.check_cookies()
    assert config.COOKIE_FILE_ENV in str(caught.value)


def test_a_readable_cookie_file_lets_the_start_run(cookie_jar):
    assert config.check_cookies() is None


def test_no_cookie_file_lets_the_start_run():
    assert config.check_cookies() is None


def test_the_janitor_deletes_an_abandoned_copy(tmp_path):
    import os
    import time

    stale = tmp_path / f"{config.COOKIE_COPY_PREFIX}old.txt"
    stale.write_text("x")
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    fresh = tmp_path / f"{config.COOKIE_COPY_PREFIX}new.txt"
    fresh.write_text("x")

    assert cleanup.sweep_orphans(tmp_path, 3600, set()) == 1
    assert not stale.exists()
    assert fresh.exists()


def test_a_probe_runs_with_the_cookie_file_in_place(cookie_jar, media_url):
    # The local media server ignores cookies. This proves that yt-dlp
    # accepts the option and that the copy is readable while it runs.
    assert downloader.probe(media_url)["title"]
