"""Background task execution with live log capture.

The backend reports progress with ``print``. Rather than swapping ``sys.stdout``
per task (racy when two tasks overlap), we install one router at start-up that
forwards each write to the task that owns the writing thread. Writes from
threads spawned *by* a task (e.g. thread pools inside the backend) go to the
most recently started task, and everything is still echoed to the real console.
"""
import sys
import threading
import traceback
from typing import Callable, Dict, Optional

from PySide6.QtCore import QObject, QThread, Signal


class _StreamRouter:
    def __init__(self, original):
        self._original = original
        self._lock = threading.Lock()
        self._sinks: Dict[int, Callable[[str], None]] = {}
        self._fallback: Optional[Callable[[str], None]] = None

    # file-like API -----------------------------------------------------
    def write(self, text):
        try:
            if self._original is not None:
                self._original.write(text)
        except Exception:
            pass
        sink = self._sinks.get(threading.get_ident()) or self._fallback
        if sink is not None and text:
            try:
                sink(text)
            except Exception:
                pass
        return len(text) if text else 0

    def flush(self):
        try:
            if self._original is not None:
                self._original.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def __getattr__(self, name):  # fileno, encoding, ...
        return getattr(self._original, name)

    # registration ------------------------------------------------------
    def register(self, ident: int, sink: Callable[[str], None]):
        with self._lock:
            self._sinks[ident] = sink
            self._fallback = sink

    def unregister(self, ident: int):
        with self._lock:
            sink = self._sinks.pop(ident, None)
            if self._fallback is sink:
                self._fallback = next(reversed(self._sinks.values()), None) if self._sinks else None


_stdout_router: Optional[_StreamRouter] = None
_stderr_router: Optional[_StreamRouter] = None


def install_stream_router():
    global _stdout_router, _stderr_router
    if _stdout_router is None:
        _stdout_router = _StreamRouter(sys.stdout)
        _stderr_router = _StreamRouter(sys.stderr)
        sys.stdout = _stdout_router
        sys.stderr = _stderr_router


class _Runner(QObject):
    log = Signal(str)
    finished = Signal(object)     # result
    failed = Signal(str)          # formatted error

    def __init__(self, fn, args, kwargs, capture_output):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs
        self._capture = capture_output

    def run(self):
        ident = threading.get_ident()
        if self._capture and _stdout_router is not None:
            _stdout_router.register(ident, self.log.emit)
            _stderr_router.register(ident, self.log.emit)
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as e:  # noqa: BLE001 - surface everything to the UI
            tb = traceback.format_exc()
            if self._capture:
                self.log.emit(tb)
            self.failed.emit(f"{type(e).__name__}: {e}")
        else:
            self.finished.emit(result)
        finally:
            if self._capture and _stdout_router is not None:
                _stdout_router.unregister(ident)
                _stderr_router.unregister(ident)


class Task(QObject):
    """Run ``fn(*args, **kwargs)`` on a QThread.

    Signals are delivered on the GUI thread. A ``threading.Event`` is available
    as ``task.stop_event`` for cooperative cancellation by the backend.
    """
    log = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)
    done = Signal()

    _live = set()   # keep references so tasks aren't garbage collected mid-run

    def __init__(self, fn, *args, capture_output=True, parent=None, **kwargs):
        super().__init__(parent)
        self.stop_event = threading.Event()
        self._thread = QThread()
        self._runner = _Runner(fn, args, kwargs, capture_output)
        self._runner.moveToThread(self._thread)
        self._thread.started.connect(self._runner.run)
        self._runner.log.connect(self.log)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)

    def start(self):
        Task._live.add(self)
        self._thread.start()
        return self

    def cancel(self):
        self.stop_event.set()

    def is_running(self) -> bool:
        return self._thread.isRunning()

    def _cleanup(self):
        self._thread.quit()
        self._thread.wait()
        self.done.emit()
        Task._live.discard(self)

    def _on_finished(self, result):
        self.succeeded.emit(result)
        self._cleanup()

    def _on_failed(self, msg):
        self.failed.emit(msg)
        self._cleanup()


def run_task(fn, *args, on_success=None, on_error=None, on_log=None, on_done=None,
             capture_output=True, **kwargs) -> Task:
    """Convenience wrapper: build, wire and start a Task."""
    t = Task(fn, *args, capture_output=capture_output, **kwargs)
    if on_log:
        t.log.connect(on_log)
    if on_success:
        t.succeeded.connect(on_success)
    if on_error:
        t.failed.connect(on_error)
    if on_done:
        t.done.connect(on_done)
    return t.start()


def run_task_with_stop(fn_factory, **handlers) -> Task:
    """Like :func:`run_task` but ``fn_factory(stop_event)`` builds the callable,
    so backend functions that accept ``stop_event=`` can be cancelled."""
    t = Task(lambda: None)
    t._runner._fn = lambda: fn_factory(t.stop_event)
    for name, sig in (("on_log", t.log), ("on_success", t.succeeded),
                      ("on_error", t.failed), ("on_done", t.done)):
        if handlers.get(name):
            sig.connect(handlers[name])
    return t.start()
