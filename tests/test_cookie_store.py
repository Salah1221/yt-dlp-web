"""The cookies that somebody pastes into the settings panel."""

import os

import pytest

from app import config, cookiestore, downloader

LINE = ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tabc123"
OTHER = ".google.com\tTRUE\t/\tTRUE\t2147483647\tNID\tdef456"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv(config.TEMP_ROOT_ENV, str(tmp_path / "work"))
    monkeypatch.delenv(config.COOKIE_FILE_ENV, raising=False)
    return config.cookie_store()


def test_nothing_saved_reports_no_source(store):
    assert cookiestore.status()["source"] == "none"


def test_a_paste_is_saved_and_described(store):
    state = cookiestore.save(f"# Netscape HTTP Cookie File\n{LINE}\n{OTHER}")
    assert state["source"] == "pasted"
    assert state["count"] == 2
    assert state["domains"] == ["google.com", "youtube.com"]
    assert state["expires"].startswith("2038")
    assert store.is_file()


def test_the_header_is_added_when_the_paste_lost_it(store):
    assert cookiestore.save(LINE)["count"] == 1


def test_the_file_is_readable_by_nobody_else(store):
    cookiestore.save(LINE)
    assert oct(store.stat().st_mode)[-3:] == "600"


def test_yt_dlp_reads_what_was_saved(store):
    cookiestore.save(LINE)
    with downloader.site_opts() as opts:
        assert open(opts["cookiefile"]).read().endswith(LINE + "\n")


def test_the_saved_file_wins_over_the_placed_one(store, tmp_path, monkeypatch):
    placed = tmp_path / "placed.txt"
    placed.write_text(f"# Netscape HTTP Cookie File\n{OTHER}\n")
    monkeypatch.setenv(config.COOKIE_FILE_ENV, str(placed))
    assert config.cookie_file() == placed
    cookiestore.save(LINE)
    assert config.cookie_file() == store


def test_the_placed_file_is_reported_and_left_alone(store, tmp_path,
                                                    monkeypatch):
    placed = tmp_path / "placed.txt"
    placed.write_text(f"# Netscape HTTP Cookie File\n{OTHER}\n")
    monkeypatch.setenv(config.COOKIE_FILE_ENV, str(placed))
    assert cookiestore.status()["source"] == "file"
    assert placed.read_text().endswith(OTHER + "\n")


def test_removing_puts_the_placed_file_back(store, tmp_path, monkeypatch):
    placed = tmp_path / "placed.txt"
    placed.write_text(f"# Netscape HTTP Cookie File\n{OTHER}\n")
    monkeypatch.setenv(config.COOKIE_FILE_ENV, str(placed))
    cookiestore.save(LINE)
    assert cookiestore.clear() is True
    assert config.cookie_file() == placed


def test_removing_nothing_says_so(store):
    assert cookiestore.clear() is False


def test_a_file_that_stopped_reading_is_called_broken(store):
    cookiestore.save(LINE)
    store.write_text("this is not a cookie file\n")
    assert cookiestore.status()["source"] == "broken"


def test_an_empty_paste_is_refused(store):
    with pytest.raises(ValueError, match="paste the cookies"):
        cookiestore.save("   \n  ")


def test_a_paste_with_no_cookie_is_refused(store):
    with pytest.raises(ValueError, match="no cookie"):
        cookiestore.save("hello world")


def test_json_is_refused_by_name(store):
    with pytest.raises(ValueError, match="JSON"):
        cookiestore.save('[{"domain": ".youtube.com", "name": "SID"}]')


def test_a_paste_that_lost_its_tabs_says_so(store):
    with pytest.raises(ValueError, match="tabs"):
        cookiestore.save(LINE.replace("\t", "    "))


def test_a_paste_larger_than_a_cookie_file_is_refused(store):
    with pytest.raises(ValueError, match="larger"):
        cookiestore.save("#" * (cookiestore.MAX_BYTES + 1))


def test_a_refused_paste_leaves_the_saved_one_in_place(store):
    cookiestore.save(LINE)
    with pytest.raises(ValueError):
        cookiestore.save("hello world")
    assert cookiestore.status()["count"] == 1
    assert not [item for item in store.parent.iterdir()
                if item.name.startswith(".cookies-")]


def test_a_broken_line_never_reaches_the_log(store, capsys):
    # yt-dlp prints the whole line it cannot read, and a line holds a
    # live session. The log of a server is not the place for it.
    with pytest.raises(ValueError):
        cookiestore.save("a-secret-value-that-must-not-be-logged")
    captured = capsys.readouterr()
    assert "a-secret-value" not in captured.out + captured.err


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root writes a folder whatever its mode says")
def test_a_folder_that_cannot_be_written_is_reported(tmp_path, monkeypatch):
    locked = tmp_path / "locked"
    locked.mkdir()
    monkeypatch.setenv(config.COOKIE_STORE_ENV, str(locked / "cookies.txt"))
    monkeypatch.delenv(config.COOKIE_FILE_ENV, raising=False)
    os.chmod(locked, 0o500)
    try:
        assert cookiestore.status()["writable"] is False
    finally:
        os.chmod(locked, 0o700)
