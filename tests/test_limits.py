import threading

from app import limits


def test_slots_allow_up_to_the_limit():
    slots = limits.JobSlots(2)
    assert slots.take() is True
    assert slots.take() is True
    assert slots.take() is False


def test_a_finished_job_frees_its_slot():
    slots = limits.JobSlots(1)
    assert slots.take() is True
    assert slots.take() is False
    slots.give_back()
    assert slots.take() is True


def test_giving_back_more_than_taken_does_not_go_negative():
    slots = limits.JobSlots(1)
    slots.give_back()
    slots.give_back()
    assert slots.take() is True
    assert slots.take() is False


def test_the_used_count_is_reported():
    slots = limits.JobSlots(2)
    assert slots.used == 0
    slots.take()
    assert slots.used == 1


def test_slots_are_safe_across_threads():
    slots = limits.JobSlots(50)
    taken = []
    start = threading.Barrier(20)

    def worker():
        start.wait(timeout=5)
        if slots.take():
            taken.append(1)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert len(taken) == 20
    assert slots.used == 20


def test_there_is_always_room_when_no_size_limit_is_set(tmp_path):
    assert limits.has_room(tmp_path, 0) is True


def test_room_is_refused_when_the_free_space_is_too_small(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "free_bytes", lambda path: 100)
    assert limits.has_room(tmp_path, 1000) is False
    assert limits.has_room(tmp_path, 100) is True


def test_free_bytes_reports_a_real_number(tmp_path):
    assert limits.free_bytes(tmp_path) > 0


def test_an_unreadable_path_reports_no_free_space(tmp_path):
    assert limits.free_bytes(tmp_path / "does" / "not" / "exist") == 0
