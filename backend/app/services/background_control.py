from __future__ import annotations

import threading
import time

# A single runtime switch for all background material processing (translation,
# and re-indexing). The workers check it at their loop boundaries, so pausing
# takes effect between files — the file in flight finishes, nothing new starts.
# Paused state is intentionally NOT persisted: a restart begins working again,
# which is the safe default for "prepare the material".
_paused = threading.Event()  # set == paused


def pause() -> None:
    _paused.set()


def resume() -> None:
    _paused.clear()


def set_paused(paused: bool) -> None:
    pause() if paused else resume()


def is_paused() -> bool:
    return _paused.is_set()


def wait_while_paused(check_interval: float = 2.0) -> None:
    """Block a background worker for as long as processing is paused."""
    while _paused.is_set():
        time.sleep(check_interval)
