"""The settings that decide how the server presents itself to YouTube."""

import pathlib
from types import SimpleNamespace

import pytest

from app import config, downloader, main


def test_the_clients_that_need_no_token_are_asked():
    # YouTube drops the streams of a client that wants a PO token, and a
    # server has no way to get one, so those clients leave nothing.
    with downloader.site_opts() as opts:
        asked = opts["extractor_args"]["youtube"]["player_client"]
    assert asked
    assert "web" not in asked
    assert "tv" in asked


def test_every_client_asked_by_default_needs_no_token():
    from yt_dlp.extractor.youtube._base import (INNERTUBE_CLIENTS,
                                                StreamingProtocol)

    protocols = (StreamingProtocol.HTTPS, StreamingProtocol.DASH,
                 StreamingProtocol.HLS)
    for name in downloader.token_free_clients():
        policies = INNERTUBE_CLIENTS[name].get("GVS_PO_TOKEN_POLICY") or {}
        for protocol in protocols:
            policy = policies.get(protocol)
            assert not (policy and policy.required), name


def test_a_client_that_wants_a_token_is_left_out():
    # web is the one yt-dlp reaches for first and the one that asks.
    assert "web" not in downloader.token_free_clients()


def test_the_operator_can_hand_the_choice_back_to_yt_dlp(monkeypatch):
    # For a server that has a plugin minting the token, where every
    # client is open again.
    monkeypatch.setenv(config.PLAYER_CLIENT_ENV, "default")
    with downloader.site_opts() as opts:
        assert opts["extractor_args"]["youtube"]["player_client"] == ["default"]


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
    assert downloader.retry_opts(error, {}) == {"extractor_args": {
        "youtube": {"player_client": ["default", "-tv_downgraded"]}}}


def test_the_client_yt_dlp_refuses_is_one_it_knows():
    # The retry drops this by name. A yt-dlp that renames it would make
    # the retry a no-op, and this says so before a user finds out.
    assert downloader.REFUSED_CLIENT in downloader.known_player_clients()


def test_a_chosen_client_list_is_left_alone(monkeypatch):
    from yt_dlp.utils import DownloadError

    monkeypatch.setenv(config.PLAYER_CLIENT_ENV, "tv")
    error = DownloadError("The page needs to be reloaded.")
    assert downloader.retry_opts(error, {}) is None


def test_every_other_error_gets_no_retry():
    from yt_dlp.utils import DownloadError

    assert downloader.retry_opts(DownloadError("HTTP Error 404"), {}) is None


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
    assert "try again" in message


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
    # The refused client goes, and the rest of what was asked stays.
    assert downloader.REFUSED_CLIENT in seen[0]["youtube"]["player_client"]
    asked = seen[1]["youtube"]["player_client"]
    assert downloader.REFUSED_CLIENT not in asked
    assert asked


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


FORMAT_ERROR = ("ERROR: [youtube] kzWg5jVuHUI: Requested format is not "
                "available. Use --list-formats for a list of available formats")


def test_the_format_error_asks_again_without_the_cookies():
    from yt_dlp.utils import DownloadError

    error = DownloadError(FORMAT_ERROR)
    assert downloader.retry_opts(error, {"cookiefile": "/tmp/c.txt"}) == {
        "cookiefile": None, "cookiesfrombrowser": None}


def test_the_browser_cookies_are_dropped_the_same_way():
    from yt_dlp.utils import DownloadError

    error = DownloadError(FORMAT_ERROR)
    assert downloader.retry_opts(
        error, {"cookiesfrombrowser": ("firefox", None, None, None)}) == {
            "cookiefile": None, "cookiesfrombrowser": None}


def test_the_format_error_without_cookies_has_nothing_left_to_try():
    from yt_dlp.utils import DownloadError

    assert downloader.retry_opts(DownloadError(FORMAT_ERROR), {}) is None


def test_the_second_attempt_carries_no_cookie(monkeypatch, tmp_path):
    from yt_dlp.utils import DownloadError

    from app import cookiestore, jobs

    monkeypatch.setenv(config.TEMP_ROOT_ENV, str(tmp_path / "work"))
    cookiestore.save(".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tabc")
    seen = []

    def fake(opts, url, download):
        seen.append(opts.get("cookiefile"))
        if len(seen) == 1:
            raise DownloadError(FORMAT_ERROR)
        (pathlib.Path(opts["paths"]["home"]) / "clip.mp4").write_bytes(b"x" * 9)
        return {"title": "no cookies, no gate"}

    monkeypatch.setattr(downloader, "_extract", fake)
    store = jobs.JobStore(tmp_path, ttl_seconds=600)
    job = store.create("https://example.com/x", "video")
    downloader.run(job, store)
    assert store.get(job.id).state == jobs.READY
    assert seen[0] is not None
    assert seen[1] is None


def test_what_yt_dlp_says_is_kept_from_the_first_attempt(monkeypatch):
    from yt_dlp.utils import DownloadError

    def fake(opts, url, download):
        # Every attempt keeps the warnings, so a failure with nothing to
        # retry can still say why it failed.
        assert opts["no_warnings"] is False
        opts["logger"].warning("Some web client https formats have been "
                               "skipped as they are missing a PO token")
        raise DownloadError(FORMAT_ERROR)

    monkeypatch.setattr(downloader, "_extract", fake)
    fake_runtimes(monkeypatch, deno=("2.5.6", True))
    with pytest.raises(downloader.Refused, match="token"):
        downloader.probe("https://example.com/x")


def test_the_message_names_sabr_when_yt_dlp_does(monkeypatch):
    from yt_dlp.utils import DownloadError

    fake_runtimes(monkeypatch, deno=("2.5.6", True))
    notes = downloader.Notes()
    notes.warning("YouTube is forcing SABR streaming for this client")
    message = downloader.explain(DownloadError(FORMAT_ERROR), "video", notes)
    assert "streaming protocol" in message


def test_the_notes_keep_nothing_that_does_not_explain_a_failure():
    notes = downloader.Notes()
    notes.debug("[debug] Loading cookies for a SECRET account")
    notes.info("[youtube] kzWg5jVuHUI: Downloading webpage")
    assert notes.lines == []
    assert notes.mentions("secret") is False


def test_the_notes_keep_the_line_that_does():
    notes = downloader.Notes()
    notes.debug("web client https formats require a GVS PO Token which was "
                "not provided")
    assert notes.mentions("po token") is True


def test_the_lines_never_reach_the_page():
    notes = downloader.Notes()
    notes.warning("web formats have been skipped: SECRET-VALUE missing a URL")
    message = downloader.explain(
        ValueError("Requested format is not available"), "video", notes)
    assert "SECRET-VALUE" not in message


def test_the_notes_do_not_grow_without_a_limit():
    notes = downloader.Notes()
    for number in range(downloader.Notes.LIMIT + 50):
        notes.debug(f"line {number} formats have been skipped")
    assert len(notes.lines) == downloader.Notes.LIMIT


def test_a_cancelled_job_is_never_retried(monkeypatch, tmp_path):
    from app import jobs

    calls = []

    def fake(opts, url, download):
        calls.append(1)
        raise jobs.JobCancelled()

    monkeypatch.setattr(downloader, "_extract", fake)
    store = jobs.JobStore(tmp_path, ttl_seconds=600)
    job = store.create("https://example.com/x", "video")
    downloader.run(job, store)
    assert len(calls) == 1
    assert store.get(job.id) is None


def test_the_reload_retry_keeps_the_other_clients(monkeypatch):
    from yt_dlp.utils import DownloadError

    error = DownloadError("The page needs to be reloaded.")
    opts = {"extractor_args": {"youtube": {
        "player_client": ["tv", "tv_downgraded", "web_embedded"]}}}
    assert downloader.retry_opts(error, opts) == {"extractor_args": {
        "youtube": {"player_client": ["tv", "web_embedded"]}}}


def test_the_reload_retry_stops_when_there_is_nothing_to_drop(monkeypatch):
    from yt_dlp.utils import DownloadError

    error = DownloadError("The page needs to be reloaded.")
    opts = {"extractor_args": {"youtube": {"player_client": ["tv"]}}}
    assert downloader.retry_opts(error, opts) is None


def test_each_attempt_keeps_its_own_notes(monkeypatch):
    from yt_dlp.utils import DownloadError

    from app import cookiestore, jobs

    fake_runtimes(monkeypatch, deno=("2.5.6", True))
    seen = []

    def fake(opts, url, download):
        seen.append(opts.get("cookiefile"))
        if len(seen) == 1:
            # The first attempt meets the token gate.
            opts["logger"].debug("web client https formats require a GVS PO "
                                 "Token which was not provided")
        else:
            opts["logger"].warning("YouTube is forcing SABR streaming for "
                                   "this client")
        raise DownloadError(FORMAT_ERROR)

    monkeypatch.setattr(downloader, "_extract", fake)
    monkeypatch.setattr(downloader, "retry_opts",
                        lambda error, opts: {"cookiefile": None,
                                             "cookiesfrombrowser": None})
    with pytest.raises(downloader.Refused) as caught:
        downloader.probe("https://example.com/x")
    # The message names what stopped the attempt that failed last, not
    # what the first one met on the way.
    assert "streaming protocol" in str(caught.value)
    assert "token" not in str(caught.value)
