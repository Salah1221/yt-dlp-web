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


def test_video_mode_with_a_max_height_caps_the_format(tmp_path):
    opts = downloader.build_opts("video", str(tmp_path), max_height=720)
    assert opts["format"] == "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b"
    assert opts["merge_output_format"] == "mp4"


def test_video_mode_without_a_max_height_is_not_capped(tmp_path):
    opts = downloader.build_opts("video", str(tmp_path), max_height=None)
    assert opts["format"] == "bv*+ba/b"


def test_a_max_height_that_is_not_positive_raises(tmp_path):
    for bad in (0, -1, -720):
        with pytest.raises(ValueError):
            downloader.build_opts("video", str(tmp_path), max_height=bad)


def test_a_max_height_that_is_not_a_whole_number_raises(tmp_path):
    for bad in ("720", 720.5, True):
        with pytest.raises(ValueError):
            downloader.build_opts("video", str(tmp_path), max_height=bad)


def test_the_max_height_is_ignored_for_audio_mode(tmp_path):
    opts = downloader.build_opts("audio", str(tmp_path), max_height=720)
    assert opts["format"] == "ba/b"


def test_the_max_height_is_ignored_for_format_mode(tmp_path):
    opts = downloader.build_opts("format", str(tmp_path), format_id="137",
                                 max_height=720)
    assert opts["format"] == "137+ba/137"


def _video(height, filesize, format_id="v"):
    return {"format_id": format_id, "vcodec": "avc1", "acodec": "none",
            "height": height, "filesize": filesize}


def _audio(filesize, format_id="a"):
    return {"format_id": format_id, "vcodec": "none", "acodec": "mp4a",
            "height": None, "filesize": filesize}


def test_build_qualities_labels_the_height():
    result = downloader.build_qualities([_video(1080, 100), _audio(10)])
    assert result[0]["height"] == 1080
    assert result[0]["label"] == "1080p"


def test_build_qualities_adds_the_best_audio_size():
    result = downloader.build_qualities(
        [_video(1080, 100), _audio(10, "a1"), _audio(25, "a2")])
    assert result[0]["filesize"] == 125


def test_build_qualities_takes_the_largest_video_of_each_height():
    result = downloader.build_qualities(
        [_video(720, 50, "v1"), _video(720, 80, "v2"), _audio(10)])
    assert len(result) == 1
    assert result[0]["filesize"] == 90


def test_build_qualities_sorts_from_high_to_low():
    result = downloader.build_qualities(
        [_video(480, 30, "v1"), _video(1080, 90, "v2"), _video(720, 60, "v3"),
         _audio(10)])
    assert [item["height"] for item in result] == [1080, 720, 480]


def test_build_qualities_gives_no_size_when_the_video_size_is_missing():
    result = downloader.build_qualities([_video(1080, None), _audio(10)])
    assert result[0]["height"] == 1080
    assert result[0]["filesize"] is None


def test_build_qualities_works_when_no_audio_size_is_known():
    result = downloader.build_qualities([_video(1080, 100), _audio(None)])
    assert result[0]["filesize"] == 100


def test_build_qualities_ignores_audio_only_and_missing_heights():
    result = downloader.build_qualities(
        [_audio(10), {"format_id": "x", "vcodec": "avc1", "height": None},
         {"format_id": "y", "vcodec": "none", "acodec": "none", "height": 720}])
    assert result == []


def test_build_qualities_accepts_the_approximate_size():
    entry = {"format_id": "v", "vcodec": "avc1", "acodec": "none",
             "height": 720, "filesize_approx": 77}
    assert downloader.build_qualities([entry])[0]["filesize"] == 77
