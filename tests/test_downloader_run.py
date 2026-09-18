import pytest

from app import downloader, jobs


@pytest.fixture()
def store(tmp_path):
    return jobs.JobStore(tmp_path, ttl_seconds=600)


def test_probe_reports_the_title_and_the_formats(media_url):
    info = downloader.probe(media_url)
    assert info["title"]
    assert isinstance(info["formats"], list)
    assert info["formats"]
    first = info["formats"][0]
    assert set(first) == {"format_id", "ext", "resolution", "fps",
                          "vcodec", "acodec", "filesize", "note"}


def test_probe_raises_for_a_bad_url():
    with pytest.raises(Exception):
        downloader.probe("http://127.0.0.1:1/missing.mp4")


def test_run_in_audio_mode_produces_an_mp3(store, media_url):
    job = store.create(media_url, "audio")
    downloader.run(job, store)
    done = store.get(job.id)
    assert done.state == jobs.READY, done.error
    assert done.filename.endswith(".mp3")
    assert done.percent == 100.0
    assert done.file_path and done.file_path.endswith(".mp3")


def test_run_in_video_mode_produces_a_file(store, media_url):
    job = store.create(media_url, "video")
    downloader.run(job, store)
    done = store.get(job.id)
    assert done.state == jobs.READY, done.error
    assert done.file_path


def test_run_publishes_progress_updates(store, media_url):
    job = store.create(media_url, "audio")
    downloader.run(job, store)
    queue = store.queue_for(job.id)
    seen = []
    while not queue.empty():
        seen.append(queue.get_nowait())
    assert seen
    assert seen[-1]["state"] == jobs.READY
    assert all("file_path" not in item for item in seen)


def test_run_records_the_error_for_a_bad_url(store):
    job = store.create("http://127.0.0.1:1/missing.mp4", "audio")
    downloader.run(job, store)
    done = store.get(job.id)
    assert done.state == jobs.ERROR
    assert done.error


def test_a_failed_run_leaves_no_folder(store, tmp_path):
    job = store.create("http://127.0.0.1:1/missing.mp4", "audio")
    downloader.run(job, store)
    assert not (tmp_path / job.id).exists()


def test_a_cancelled_run_removes_the_job_and_the_folder(store, media_url, tmp_path):
    job = store.create(media_url, "audio")
    store.update(job.id, cancelled=True)
    downloader.run(job, store)
    assert store.get(job.id) is None
    assert not (tmp_path / job.id).exists()


def test_probe_reports_a_quality_list(media_url):
    info = downloader.probe(media_url)
    assert isinstance(info["qualities"], list)
    for item in info["qualities"]:
        assert set(item) == {"height", "label", "filesize"}
        assert item["label"].endswith("p")


def test_run_with_a_max_height_produces_a_file(store, media_url):
    job = store.create(media_url, "video", max_height=240)
    assert job.max_height == 240
    downloader.run(job, store)
    done = store.get(job.id)
    assert done.state == jobs.READY, done.error
    assert done.file_path
