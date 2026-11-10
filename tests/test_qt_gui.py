"""Desktop GUI tests (PySide6). Skipped when Qt isn't available."""
import os
import subprocess
import sys

import pytest

pytest.importorskip("PySide6.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(os.path.dirname(HERE), "seed_vault")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dataframe_model_checkboxes(qapp):
    import pandas as pd
    from PySide6.QtCore import Qt
    from seed_vault.qt.widgets import DataFrameModel

    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    m = DataFrameModel(df, check_col="sel")
    changed = []
    m.selection_changed.connect(changed.append)
    assert m.columnCount() == 3 and m.rowCount() == 3
    assert m.headerData(0, Qt.Horizontal) == "✓"
    assert m.setData(m.index(1, 0), Qt.Checked, Qt.CheckStateRole)
    assert df["sel"].tolist() == [False, True, False]
    m.set_checked([0, 2], True)
    assert df["sel"].all() and changed == [[1], [0, 2]]


def test_log_view_handles_carriage_returns(qapp):
    from seed_vault.qt.widgets import LogView
    v = LogView()
    v.append_text("start\n")
    v.append_text("progress 10%\r")
    v.append_text("progress 90%\r")
    v.append_text("progress 100%\ndone\n")
    assert v.toPlainText().splitlines() == ["start", "progress 100%", "done"]


def test_worker_captures_output_and_result(qapp):
    from PySide6.QtCore import QEventLoop, QTimer
    from seed_vault.qt.workers import install_stream_router, run_task

    install_stream_router()
    logs, results = [], []

    def job(x):
        print("working on", x)
        return x * 2

    loop = QEventLoop()
    run_task(job, 21, on_log=logs.append, on_success=results.append, on_done=loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert results == [42]
    assert "working on 21" in "".join(logs)


def _run_gui_script(script, tmp_path):
    """Run a GUI script in a subprocess, restoring the package config files it may rewrite."""
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    import seed_vault
    pkg = os.path.dirname(seed_vault.__file__)
    touched = [os.path.join(pkg, "service", "config.cfg"), os.path.join(pkg, "models", "clients.csv")]
    backups = {}
    for p in touched:
        if os.path.exists(p):
            with open(p, "rb") as f:
                backups[p] = f.read()
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu")
    try:
        proc = subprocess.run([sys.executable, os.path.join(HERE, script), str(tmp_path)],
                              cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    finally:
        for p in touched:
            if p in backups:
                with open(p, "wb") as f:
                    f.write(backups[p])
            elif os.path.exists(p):
                os.remove(p)
    report = "\n".join(l for l in proc.stdout.splitlines() if l.startswith(("PASS", "FAIL", "FAILURES")))
    assert proc.returncode == 0, report + "\n" + proc.stderr[-3000:]
    assert "FAILURES: []" in proc.stdout


def test_end_to_end_workflows(tmp_path):
    """Full event-based + continuous workflow, DB explorer and settings, using ObsPy sample data."""
    _run_gui_script("qt_e2e_script.py", tmp_path)


def test_reported_issue_regressions(tmp_path):
    """Composite clients hidden, settings editors, stable table order, station view, wheel scrolling."""
    _run_gui_script("qt_regressions_script.py", tmp_path)
