"""The settings that decide how the server presents itself to YouTube."""

import pathlib
from types import SimpleNamespace

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


def fake_runtimes(monkeypatch, **installed):
    """Say which runtimes are installed, and whether yt-dlp takes them.

    Pass a version and a verdict per name: node=("20.20.2", False).
    """
    def info(name, path=None):
        if name not in installed:
            return None
        version, supported = installed[name]
        return SimpleNamespace(name=name, path=f"/usr/bin/{name}",
                               version=version, supported=supported)

    monkeypatch.setattr(downloader, "runtime_info", info)


def test_a_runtime_that_is_installed_is_used_without_being_asked(monkeypatch):
    # yt-dlp enables deno and nothing else, so a server with node and no
    # deno would run YouTube with no runtime at all.
    fake_runtimes(monkeypatch, node=("22.1.0", True))
    assert downloader.js_runtime_auto() == {"node": {}}
    with downloader.site_opts() as opts:
        assert opts["js_runtimes"] == {"node": {}}


def test_a_present_deno_is_left_to_yt_dlp(monkeypatch):
    fake_runtimes(monkeypatch, deno=("2.5.6", True), node=("22.1.0", True))
    assert downloader.js_runtime_auto() is None
    with downloader.site_opts() as opts:
        assert "js_runtimes" not in opts


def test_a_node_that_is_too_old_is_not_used(monkeypatch):
    # yt-dlp wants node 22, and a server carrying 20 has a node that
    # counts for nothing. Enabling it would look like a fix and be none.
    fake_runtimes(monkeypatch, node=("20.20.2", False))
    assert downloader.js_runtime_auto() is None
    assert downloader.js_runtime_ready() is False


def test_the_trouble_names_both_versions(monkeypatch):
    fake_runtimes(monkeypatch, node=("20.20.2", False))
    trouble = downloader.js_runtime_trouble()
    assert "20.20.2" in trouble
    assert "22" in trouble


def test_a_runtime_after_the_old_one_is_still_taken(monkeypatch):
    fake_runtimes(monkeypatch, node=("20.20.2", False), bun=("1.3.11", True))
    assert downloader.js_runtime_auto() == {"bun": {}}
    assert downloader.js_runtime_ready() is True


def test_what_the_operator_asked_for_wins(monkeypatch):
    monkeypatch.setenv(config.JS_RUNTIME_ENV, "bun")
    fake_runtimes(monkeypatch, deno=("2.5.6", True), bun=("1.3.11", True))
    with downloader.site_opts() as opts:
        assert opts["js_runtimes"] == {"bun": {}}


def test_no_runtime_anywhere_is_not_ready(monkeypatch):
    fake_runtimes(monkeypatch)
    assert downloader.js_runtime_ready() is False
    assert downloader.js_runtime_trouble() == "no JavaScript runtime is installed"


def test_a_named_runtime_that_is_absent_is_not_ready(monkeypatch):
    monkeypatch.setenv(config.JS_RUNTIME_ENV, "deno")
    fake_runtimes(monkeypatch, node=("22.1.0", True))
    assert downloader.js_runtime_ready() is False


def test_the_runtime_warning_tells_you_to_install_one(monkeypatch, caplog):
    fake_runtimes(monkeypatch)
    main.warn_about_the_js_runtime()
    assert config.JS_RUNTIME_ENV in caplog.text
    assert "no JavaScript runtime is installed" in caplog.text


def test_the_warning_names_a_runtime_that_is_too_old(monkeypatch, caplog):
    fake_runtimes(monkeypatch, node=("20.20.2", False))
    main.warn_about_the_js_runtime()
    assert "20.20.2" in caplog.text


def test_a_present_deno_raises_no_warning(monkeypatch, caplog):
    fake_runtimes(monkeypatch, deno=("2.5.6", True))
    main.warn_about_the_js_runtime()
    assert caplog.text == ""


def test_the_runtime_it_found_by_itself_is_named_in_the_log(monkeypatch, caplog):
    import logging

    caplog.set_level(logging.INFO)
    fake_runtimes(monkeypatch, node=("22.1.0", True))
    main.warn_about_the_js_runtime()
    assert "node" in caplog.text


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


def test_the_reload_message_says_to_try_again_when_a_runtime_is_there(
        monkeypatch):
    from yt_dlp.utils import DownloadError

    fake_runtimes(monkeypatch, deno=("2.5.6", True))
    message = downloader.explain(DownloadError("The page needs to be reloaded."))
    assert "try again" in message


def test_the_reload_message_names_the_runtime_when_there_is_none(monkeypatch):
    from yt_dlp.utils import DownloadError

    fake_runtimes(monkeypatch)
    message = downloader.explain(DownloadError("The page needs to be reloaded."))
    assert config.JS_RUNTIME_ENV in message


def test_the_format_message_names_the_runtime_when_there_is_none(monkeypatch):
    from yt_dlp.utils import DownloadError

    fake_runtimes(monkeypatch)
    message = downloader.explain(
        DownloadError("ERROR: Requested format is not available. "
                      "Use --list-formats for a list of available formats"))
    assert config.JS_RUNTIME_ENV in message
    assert "--list-formats" not in message


def test_the_format_message_sends_a_chosen_format_back_to_check(monkeypatch):
    from yt_dlp.utils import DownloadError

    fake_runtimes(monkeypatch, deno=("2.5.6", True))
    message = downloader.explain(
        DownloadError("Requested format is not available"), "format")
    assert "Press Check again" in message


def test_the_format_message_for_the_buttons_says_to_try_again(monkeypatch):
    from yt_dlp.utils import DownloadError

    fake_runtimes(monkeypatch, deno=("2.5.6", True))
    message = downloader.explain(
        DownloadError("Requested format is not available"), "video")
    assert "Try again" in message


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

    fake_runtimes(monkeypatch)

    def fake(opts, url, download):
        raise DownloadError("The page needs to be reloaded.")

    monkeypatch.setattr(downloader, "_extract", fake)
    with pytest.raises(ValueError, match="JavaScript runtime"):
        downloader.probe("https://example.com/x")
