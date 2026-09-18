import pytest

from app import downloader


def test_video_mode_merges_into_mp4_with_faststart(tmp_path):
    opts = downloader.build_opts("video", str(tmp_path))
    assert opts["format"] == "bv*+ba/b"
    assert opts["merge_output_format"] == "mp4"
    assert opts["postprocessor_args"]["merger"] == ["-movflags", "+faststart"]
    assert "postprocessors" not in opts


def test_audio_mode_extracts_mp3_at_192(tmp_path):
    opts = downloader.build_opts("audio", str(tmp_path))
    assert opts["format"] == "ba/b"
    post = opts["postprocessors"][0]
    assert post["key"] == "FFmpegExtractAudio"
    assert post["preferredcodec"] == "mp3"
    assert post["preferredquality"] == "192"
    assert "merge_output_format" not in opts


def test_format_mode_adds_best_audio_with_a_fallback(tmp_path):
    opts = downloader.build_opts("format", str(tmp_path), format_id="137")
    assert opts["format"] == "137+ba/137"
    assert "postprocessors" not in opts
    assert "merge_output_format" not in opts


def test_format_mode_needs_a_format_id(tmp_path):
    with pytest.raises(ValueError):
        downloader.build_opts("format", str(tmp_path))


def test_an_unknown_mode_raises(tmp_path):
    with pytest.raises(ValueError):
        downloader.build_opts("gif", str(tmp_path))


def test_every_mode_writes_inside_the_work_folder(tmp_path):
    for mode, format_id in (("video", None), ("audio", None), ("format", "22")):
        opts = downloader.build_opts(mode, str(tmp_path), format_id=format_id)
        assert opts["outtmpl"].startswith(str(tmp_path))
        assert opts["noplaylist"] is True


def test_the_hooks_are_attached_when_given(tmp_path):
    def hook(data):
        return None

    opts = downloader.build_opts("audio", str(tmp_path),
                                 progress_hook=hook, postprocessor_hook=hook)
    assert opts["progress_hooks"] == [hook]
    assert opts["postprocessor_hooks"] == [hook]


def test_the_hook_lists_are_empty_when_not_given(tmp_path):
    opts = downloader.build_opts("audio", str(tmp_path))
    assert opts["progress_hooks"] == []
    assert opts["postprocessor_hooks"] == []


def test_find_output_returns_none_for_an_empty_folder(tmp_path):
    assert downloader.find_output(tmp_path) is None


def test_find_output_ignores_the_partial_files(tmp_path):
    (tmp_path / "song.mp3").write_bytes(b"x" * 10)
    (tmp_path / "song.f140.m4a.part").write_bytes(b"x" * 9000)
    (tmp_path / "song.ytdl").write_bytes(b"x" * 9000)
    assert downloader.find_output(tmp_path).name == "song.mp3"


def test_find_output_takes_the_largest_finished_file(tmp_path):
    (tmp_path / "small.mp4").write_bytes(b"x" * 10)
    (tmp_path / "large.mp4").write_bytes(b"x" * 100)
    assert downloader.find_output(tmp_path).name == "large.mp4"


def test_find_output_ignores_folders(tmp_path):
    (tmp_path / "fragments").mkdir()
    (tmp_path / "song.mp3").write_bytes(b"x")
    assert downloader.find_output(tmp_path).name == "song.mp3"
