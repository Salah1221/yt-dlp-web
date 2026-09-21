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
    assert downloader.next_fallback(error, {}, ()) == ("clients", {
        "extractor_args": {
            "youtube": {"player_client": ["default", "-tv_downgraded"]}}})


def test_the_client_yt_dlp_refuses_is_one_it_knows():
    # The retry drops this by name. A yt-dlp that renames it would make
    # the retry a no-op, and this says so before a user finds out.
    assert downloader.REFUSED_CLIENT in downloader.known_player_clients()


def test_a_chosen_client_list_is_left_alone(monkeypatch):
    from yt_dlp.utils import DownloadError

    monkeypatch.setenv(config.PLAYER_CLIENT_ENV, "tv")
    error = DownloadError("The page needs to be reloaded.")
    # The named list is theirs to keep, so only the cookies may go, and
    # there are none here.
    assert downloader.next_fallback(error, {}, ()) is None


def test_every_other_error_gets_no_retry():
    from yt_dlp.utils import DownloadError

    assert downloader.next_fallback(
        DownloadError("HTTP Error 404"), {}, ()) is None


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
    assert downloader.next_fallback(
        error, {"cookiefile": "/tmp/c.txt"}, ("clients",)) == (
            "cookies", {"cookiefile": None, "cookiesfrombrowser": None})


def test_the_browser_cookies_are_dropped_the_same_way():
    from yt_dlp.utils import DownloadError

    error = DownloadError(FORMAT_ERROR)
    assert downloader.next_fallback(
        error, {"cookiesfrombrowser": ("firefox", None, None, None)},
        ("clients",)) == (
            "cookies", {"cookiefile": None, "cookiesfrombrowser": None})


def test_the_format_error_without_cookies_has_nothing_left_to_try():
    from yt_dlp.utils import DownloadError

    assert downloader.next_fallback(
        DownloadError(FORMAT_ERROR), {}, ("clients",)) is None


def test_the_ladder_drops_the_refused_client_then_the_cookies(monkeypatch,
                                                              tmp_path):
    from yt_dlp.utils import DownloadError

    from app import cookiestore, jobs

    monkeypatch.setenv(config.TEMP_ROOT_ENV, str(tmp_path / "work"))
    cookiestore.save(".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tabc")
    seen = []

    def fake(opts, url, download):
        seen.append((opts.get("cookiefile"),
                     opts["extractor_args"]["youtube"]["player_client"]))
        if len(seen) < 3:
            raise DownloadError(FORMAT_ERROR)
        (pathlib.Path(opts["paths"]["home"]) / "clip.mp4").write_bytes(b"x" * 9)
        return {"title": "the third time"}

    monkeypatch.setattr(downloader, "_extract", fake)
    store = jobs.JobStore(tmp_path, ttl_seconds=600)
    job = store.create("https://example.com/x", "video")
    downloader.run(job, store)

    assert store.get(job.id).state == jobs.READY
    # The sign in is kept while the cheap rung is taken.
    assert seen[0][0] is not None
    assert downloader.REFUSED_CLIENT in seen[0][1]
    assert seen[1][0] is not None
    assert downloader.REFUSED_CLIENT not in seen[1][1]
    # Then the cookies go, and the reduced list stays reduced.
    assert seen[2][0] is None
    assert seen[2][1] == seen[1][1]


def test_the_reload_error_walks_the_same_ladder(monkeypatch, tmp_path):
    from yt_dlp.utils import DownloadError

    from app import cookiestore, jobs

    monkeypatch.setenv(config.TEMP_ROOT_ENV, str(tmp_path / "work"))
    cookiestore.save(".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tabc")
    seen = []

    def fake(opts, url, download):
        seen.append(opts.get("cookiefile"))
        if len(seen) < 3:
            # This is what YouTube says to a signed in visitor on the
            # clients it has stopped serving.
            raise DownloadError("ERROR: [youtube] x: The page needs to be "
                                "reloaded.")
        (pathlib.Path(opts["paths"]["home"]) / "clip.mp4").write_bytes(b"x" * 9)
        return {"title": "as nobody"}

    monkeypatch.setattr(downloader, "_extract", fake)
    store = jobs.JobStore(tmp_path, ttl_seconds=600)
    job = store.create("https://example.com/x", "video")
    downloader.run(job, store)

    assert store.get(job.id).state == jobs.READY
    assert seen[2] is None


def test_the_message_says_it_was_tried_both_ways(monkeypatch):
    from yt_dlp.utils import DownloadError

    fake_runtimes(monkeypatch, deno=("2.5.6", True))
    error = DownloadError("The page needs to be reloaded.")
    assert "without them" in downloader.explain(
        error, "video", None, ("clients", "cookies"))
    assert "without them" not in downloader.explain(error, "video", None, ())


def test_a_ladder_rung_is_taken_once(monkeypatch):
    from yt_dlp.utils import DownloadError

    error = DownloadError(FORMAT_ERROR)
    opts = {"cookiefile": "/tmp/c.txt",
            "extractor_args": {"youtube": {"player_client": ["tv"]}}}
    assert downloader.next_fallback(error, opts, ("cookies",)) is None


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
    assert downloader.next_fallback(error, opts, ()) == ("clients", {
        "extractor_args": {
            "youtube": {"player_client": ["tv", "web_embedded"]}}})


def test_the_reload_retry_stops_when_there_is_nothing_to_drop(monkeypatch):
    from yt_dlp.utils import DownloadError

    error = DownloadError("The page needs to be reloaded.")
    opts = {"extractor_args": {"youtube": {"player_client": ["tv"]}}}
    assert downloader.next_fallback(error, opts, ()) is None


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
    monkeypatch.setattr(downloader, "next_fallback",
                        lambda error, opts, spent: None if spent else
                        ("cookies", {"cookiefile": None,
                                     "cookiesfrombrowser": None}))
    with pytest.raises(downloader.Refused) as caught:
        downloader.probe("https://example.com/x")
    # The message names what stopped the attempt that failed last, not
    # what the first one met on the way.
    assert "streaming protocol" in str(caught.value)
    assert "token" not in str(caught.value)


# ---- the proof token server ---------------------------------------------

import http.server
import threading


class _Ping(http.server.BaseHTTPRequestHandler):
    """Answers /ping the way the bgutil server does, and nothing else."""

    version = "2.0.0"

    def do_GET(self):
        if self.path != "/ping":
            self.send_error(404)
            return
        body = f'{{"server_uptime": 1.0, "version": "{self.version}"}}'.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return None


@pytest.fixture()
def token_server(monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Ping)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv(config.POT_SERVER_ENV, url)
    monkeypatch.setattr(downloader, "_token_server_seen",
                        {"at": 0.0, "ready": False, "version": None})
    yield url
    server.shutdown()


@pytest.fixture()
def no_token_server(monkeypatch):
    monkeypatch.setenv(config.POT_SERVER_ENV, "off")
    monkeypatch.setattr(downloader, "_token_server_seen",
                        {"at": 0.0, "ready": False, "version": None})


def test_a_token_server_that_answers_hands_the_clients_to_yt_dlp(token_server):
    assert downloader.token_server_ready() is True
    assert downloader.token_server_version() == "2.0.0"
    assert downloader.default_clients() == ()
    with downloader.site_opts() as opts:
        youtube = (opts.get("extractor_args") or {}).get("youtube")
        assert youtube is None


def test_a_token_server_elsewhere_is_named_to_the_plugin(token_server):
    with downloader.site_opts() as opts:
        assert opts["extractor_args"]["youtubepot-bgutilhttp"] == {
            "base_url": [token_server]}


def test_the_default_address_needs_no_saying(monkeypatch):
    # The plugin looks at this one by itself.
    monkeypatch.delenv(config.POT_SERVER_ENV, raising=False)
    assert config.pot_server() == config.POT_SERVER


def test_no_server_keeps_the_token_free_clients(no_token_server):
    assert downloader.token_server_ready() is False
    assert downloader.default_clients() == downloader.token_free_clients()


def test_a_closed_port_counts_as_no_server(monkeypatch):
    monkeypatch.setenv(config.POT_SERVER_ENV, "http://127.0.0.1:1")
    monkeypatch.setattr(downloader, "_token_server_seen",
                        {"at": 0.0, "ready": False, "version": None})
    assert downloader.token_server_ready() is False
    assert downloader.default_clients() == downloader.token_free_clients()


def test_the_server_is_asked_once_a_minute_not_once_a_job(token_server,
                                                         monkeypatch):
    calls = []
    real = downloader.urllib.request.urlopen

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(downloader.urllib.request, "urlopen", counting)
    for _ in range(5):
        downloader.token_server_ready()
    assert len(calls) == 1


def test_off_is_a_word_for_no_server(monkeypatch):
    for word in ("off", "none", "0", "no", "OFF"):
        monkeypatch.setenv(config.POT_SERVER_ENV, word)
        assert config.pot_server() is None


def test_the_operator_choice_of_clients_still_wins(token_server, monkeypatch):
    monkeypatch.setenv(config.PLAYER_CLIENT_ENV, "tv")
    with downloader.site_opts() as opts:
        assert opts["extractor_args"]["youtube"]["player_client"] == ["tv"]


def test_the_startup_line_names_a_server_that_answers(token_server, caplog):
    import logging

    caplog.set_level(logging.INFO)
    main.say_which_youtube_clients()
    assert "2.0.0" in caplog.text
    assert "yt-dlp picks" in caplog.text


def test_the_startup_line_says_where_to_get_one(no_token_server, caplog,
                                                  monkeypatch):
    import logging

    caplog.set_level(logging.INFO)
    monkeypatch.setenv(config.POT_SERVER_ENV, "http://127.0.0.1:1")
    main.say_which_youtube_clients()
    assert "need no token" in caplog.text
    assert "section 12" in caplog.text


# ---------------------------------------------------------------------------
# The robot check walks the ladder too.
# ---------------------------------------------------------------------------

BOT_ERROR = ("ERROR: [youtube] abc: Sign in to confirm you are not a bot. "
             "Use --cookies-from-browser or --cookies for the authentication.")


def _bot_error():
    from yt_dlp.utils import DownloadError
    return DownloadError(BOT_ERROR)


def test_a_robot_check_drops_the_cookies_and_asks_again():
    """Signing in is what puts this server on the worst clients.

    The ladder already knows that. It was never walked for a robot
    check, so a cookie that provoked the check was asked with forever.
    """
    step = downloader.next_fallback(
        _bot_error(), {"cookiefile": "/tmp/jar.txt"}, ())
    assert step is not None
    name, changes = step
    assert name == "cookies"
    assert changes["cookiefile"] is None
    assert changes["cookiesfrombrowser"] is None


def test_a_robot_check_does_not_bother_with_the_client_rung():
    # A robot check is about who is asking, not about which client
    # answered, so dropping a client has nothing to offer it.
    step = downloader.next_fallback(
        _bot_error(), {"cookiefile": "/tmp/jar.txt"}, ())
    assert step[0] != "clients"


def test_a_robot_check_stops_once_the_cookies_are_spent():
    assert downloader.next_fallback(
        _bot_error(), {"cookiefile": "/tmp/jar.txt"}, ("cookies",)) is None


def test_a_robot_check_with_no_cookies_has_no_rung_left():
    assert downloader.next_fallback(_bot_error(), {}, ()) is None


def test_the_token_server_is_named_for_the_guard(monkeypatch):
    """The guard blocks loopback, and the token is minted on loopback.

    Without naming it, every download goes out with no token, which is
    the one thing the token server exists to prevent.
    """
    monkeypatch.setenv(config.POT_SERVER_ENV, "http://127.0.0.1:4416")
    assert downloader.token_server_targets() == (("127.0.0.1", 4416),)


def test_no_token_server_names_nothing_for_the_guard(monkeypatch):
    monkeypatch.setenv(config.POT_SERVER_ENV, "off")
    assert downloader.token_server_targets() == ()
