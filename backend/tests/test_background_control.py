import threading
import time

from fastapi.testclient import TestClient

from app.main import app
from app.services import background_control


def test_pause_and_resume_flip_the_flag():
    background_control.resume()
    assert not background_control.is_paused()
    background_control.pause()
    assert background_control.is_paused()
    background_control.resume()
    assert not background_control.is_paused()


def test_a_paused_worker_blocks_then_continues_on_resume():
    background_control.pause()
    released = threading.Event()

    def worker():
        background_control.wait_while_paused(check_interval=0.05)
        released.set()

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.2)
    assert not released.is_set(), "worker ran while paused"

    background_control.resume()
    t.join(timeout=2)
    assert released.is_set(), "worker did not continue after resume"


def test_endpoint_toggles_and_status_reports_it():
    with TestClient(app) as client:
        assert client.post("/admin/background", json={"enabled": False}).json() == {
            "background_enabled": False
        }
        assert client.get("/status").json()["background_enabled"] is False

        client.post("/admin/background", json={"enabled": True})
        assert client.get("/status").json()["background_enabled"] is True
    background_control.resume()  # leave the flag clean for other tests
