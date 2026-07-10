from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class ApiWorker(QRunnable):
    """Reusable background worker for blocking API calls."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


# keep in-flight workers referenced: without this, Python may garbage-collect
# the worker (and its WorkerSignals QObject) after the pool's autoDelete,
# dropping the queued finished/failed delivery - the UI then never gets the
# result and anything disabled while "busy" stays disabled forever
_in_flight: set[ApiWorker] = set()


def run_async(
    fn: Callable[..., Any],
    *args: Any,
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> None:
    """Run a blocking call on the global thread pool; callbacks fire on the UI thread."""
    worker = ApiWorker(fn, *args, **kwargs)
    worker.setAutoDelete(False)
    _in_flight.add(worker)

    if on_done is not None:
        worker.signals.finished.connect(on_done)
    if on_error is not None:
        worker.signals.failed.connect(on_error)

    def _release(*_args: Any) -> None:
        _in_flight.discard(worker)

    worker.signals.finished.connect(_release)
    worker.signals.failed.connect(_release)
    QThreadPool.globalInstance().start(worker)
