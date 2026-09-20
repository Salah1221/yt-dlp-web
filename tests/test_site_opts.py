"""The settings that decide how the server presents itself to YouTube."""

import pathlib

import pytest

from app import config, downloader, main


def test_no_setting_asks_for_no_client():
    with downloader.site_opts() as opts:
        assert "extractor_args" not in opts


def test_the_client_list_reaches_yt_dlp(monkeypatch):
    monkeypatch.setenv(config.PLAYER_CLIENT_ENV, "tv, android_vr")
    with downloader.site_opts() as opts:
        assert opts["extractor_args"] == {
            "youtube": {"player_client": ["tv", "android_vr"]}}


def test_a_blank_client_list_is_no_setting(monkeypatch):
    monkeypatch.setenv(config.PLAYER_CLIENT_ENV, " , ")
    assert config.player_clients() is None


def test_every_name_in_the_client_list_is_one_yt_dlp_knows(monkeypatch):
    monkeypatch.setenv(config.PLAYER_CLIENT_ENV, "tv,not_a_client")
    with pytest.raises(RuntimeError) as caught:
        downloader.check_player_clients()
    assert "not_a_client" in str(caught.value)


def test_the_three_yt_dlp_words_pass_the_client_check(monkeypatch):
    monkeypatch.setenv(config.PLAYER_CLIENT_ENV, "default,all,-web")
    assert downloader.check_player_clients() is None


def test_a_known_client_passes_the_check(monkeypatch):
    monkeypatch.setenv(config.PLAYER_CLIENT_ENV, "tv")
    assert downloader.check_player_clients() is None


def test_no_runtime_setting_leaves_the_yt_dlp_default(monkeypatch):
    with downloader.site_opts() as opts:
        assert "js_runtimes" not in opts


def test_the_runtime_reaches_yt_dlp_with_its_path(monkeypatch):
    monkeypatch.setenv(config.JS_RUNTIME_ENV, "node:/usr/bin/node, bun")
    with downloader.site_opts() as opts:
        assert opts["js_runtimes"] == {"node": {"path": "/usr/bin/node"},
                                       "bun": {}}


def test_an_unknown_runtime_stops_the_start(monkeypatch):
    monkeypatch.setenv(config.JS_RUNTIME_ENV, "rhino")
    with pytest.raises(RuntimeError) as caught:
        config.check_js_runtimes()
    assert "rhino" in str(caught.value)


def test_a_known_runtime_lets_the_start_run(monkeypatch):
    monkeypatch.setenv(config.JS_RUNTIME_ENV, "deno")
    assert config.check_js_runtimes() is None


def test_yt_dlp_accepts_the_runtime_setting(monkeypatch):
    # yt-dlp checks the names itself when it builds. This proves that the
    # shape of the value is the shape it wants.
    from yt_dlp import YoutubeDL

    monkeypatch.setenv(config.JS_RUNTIME_ENV, "node")
    with downloader.site_opts() as opts:
        with YoutubeDL({"quiet": True, **opts}) as ydl:
            assert ydl.params["js_runtimes"] == {"node": {}}


def test_the_runtime_warning_names_a_runtime_that_is_there(monkeypatch, caplog):
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    monkeypatch.setattr(config, "js_runtime_on_path", lambda: "node")
    main.warn_about_the_js_runtime()
    assert config.JS_RUNTIME_ENV in caplog.text
    assert "node" in caplog.text


def test_the_runtime_warning_tells_you_to_install_one(monkeypatch, caplog):
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    monkeypatch.setattr(config, "js_runtime_on_path", lambda: None)
    main.warn_about_the_js_runtime()
    assert "Install deno" in caplog.text


def test_a_present_deno_raises_no_warning(monkeypatch, caplog):
    monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/deno")
    main.warn_about_the_js_runtime()
    assert caplog.text == ""


def test_a_named_runtime_raises_no_warning(monkeypatch, caplog):
    monkeypatch.setenv(config.JS_RUNTIME_ENV, "node")
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    main.warn_about_the_js_runtime()
    assert caplog.text == ""


def test_the_reload_error_asks_the_rest_of_the_clients():
    from yt_dlp.utils import DownloadError

    error = DownloadError("ERROR: [youtube] kzWg5jVuHUI: "
                          "The page needs to be reloaded.")
    assert downloader.retry_opts(error) == {"extractor_args": {
        "youtube": {"player_client": ["default", "-tv_downgraded"]}}}


def test_the_client_yt_dlp_refuses_is_one_it_knows():
    # The retry drops this by name. A yt-dlp that renames it would make
    # the retry a no-op, and this says so before a user finds out.
    assert downloader.REFUSED_CLIENT in downloader.known_player_clients()


def test_a_chosen_client_list_is_left_alone(monkeypatch):
    from yt_dlp.utils import DownloadError

    monkeypatch.setenv(config.PLAYER_CLIENT_ENV, "tv")
    error = DownloadError("The page needs to be reloaded.")
    assert downloader.retry_opts(error) is None


def test_every_other_error_gets_no_retry():
    from yt_dlp.utils import DownloadError

    assert downloader.retry_opts(DownloadError("HTTP Error 404")) is None


def test_the_reload_message_names_what_to_check():
    from yt_dlp.utils import DownloadError

    message = downloader.explain(DownloadError("The page needs to be reloaded."))
    assert "try again" in message
    assert config.JS_RUNTIME_ENV in message


def test_probe_asks_a_second_time_and_reports_the_second_answer(monkeypatch):
    from yt_dlp.utils import DownloadError

    seen = []

    def fake(opts, url, download):
        seen.append(opts.get("extractor_args"))
        if len(seen) == 1:
            raise DownloadError("The page needs to be reloaded.")
        return {"title": "it worked the second time", "formats": []}

    monkeypatch.setattr(downloader, "_extract", fake)
    assert downloader.probe("https://example.com/x")["title"] == \
        "it worked the second time"
    assert seen[0] is None
    assert seen[1]["youtube"]["player_client"] == ["default", "-tv_downgraded"]


def test_a_job_asks_a_second_time_as_well(monkeypatch, tmp_path):
    from yt_dlp.utils import DownloadError

    from app import jobs

    seen = []

    def fake(opts, url, download):
        seen.append(opts.get("extractor_args"))
        if len(seen) == 1:
            raise DownloadError("The page needs to be reloaded.")
        (pathlib.Path(opts["paths"]["home"]) / "clip.mp4").write_bytes(b"x" * 10)
        return {"title": "second time"}

    monkeypatch.setattr(downloader, "_extract", fake)
    store = jobs.JobStore(tmp_path, ttl_seconds=600)
    job = store.create("https://example.com/x", "video")
    downloader.run(job, store)
    assert store.get(job.id).state == jobs.READY
    assert len(seen) == 2


def test_a_second_refusal_is_reported_in_words(monkeypatch):
    from yt_dlp.utils import DownloadError

    def fake(opts, url, download):
        raise DownloadError("The page needs to be reloaded.")

    monkeypatch.setattr(downloader, "_extract", fake)
    with pytest.raises(ValueError, match="JavaScript runtime"):
        downloader.probe("https://example.com/x")
