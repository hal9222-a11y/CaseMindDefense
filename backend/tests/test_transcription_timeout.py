"""A single pathological audio file must not wedge the transcription queue:
_drain_segments enforces a wall-clock deadline, banking partial results."""
from app.services.transcription_service import _drain_segments


class _Seg:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


def _many_segments(n):
    for i in range(n):
        yield _Seg(i, i + 1, "x" * 200)  # 200 chars each -> flushes every ~5


def test_deadline_stops_a_runaway_file_but_banks_partial():
    # a fake clock that ticks one second per segment; deadline at t=10 means the
    # generator is abandoned partway even though it would yield 1000 segments
    ticks = iter(range(10_000))
    now = lambda: next(ticks)
    chunks, truncated = _drain_segments(_many_segments(1000), deadline=10, now=now)
    assert truncated is True
    assert 0 < len(chunks) < 1000  # some banked, not all consumed


def test_normal_file_drains_fully_and_is_not_flagged():
    chunks, truncated = _drain_segments(_many_segments(6), deadline=10, now=lambda: 0)
    assert truncated is False
    assert chunks and chunks[0]["source_location"].startswith("time:00:00-")


if __name__ == "__main__":
    test_deadline_stops_a_runaway_file_but_banks_partial()
    test_normal_file_drains_fully_and_is_not_flagged()
    print("ok")
