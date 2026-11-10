"""SEED Vault desktop application (Qt / PySide6).

Run with ``seed-vault`` (or ``python -m seed_vault.qt``).
"""
import os
import sys

# Chromium flags must be set before QApplication exists.
_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split()
if "--log-level" not in " ".join(_flags):
    _flags.append("--log-level=3")          # only fatal Chromium messages (hides benign NSS/GPU noise)
if hasattr(os, "geteuid") and os.geteuid() == 0 and "--no-sandbox" not in _flags:
    _flags.append("--no-sandbox")           # required when run as root / in containers
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(_flags)

# Benign start-up warnings from QtWebEngine that users can't act on.
_QUIET_MESSAGES = ("GBM is not supported", "propagateSizeHints")

from PySide6.QtCore import QCoreApplication, QSettings, Qt, qInstallMessageHandler  # noqa: E402
import PySide6.QtWebEngineWidgets  # noqa: E402,F401  (must be imported before QApplication exists)
from PySide6.QtWidgets import (QApplication, QFrame, QMainWindow, QTabBar, QVBoxLayout,  # noqa: E402
                               QMessageBox, QStackedWidget, QWidget)

from seed_vault.qt.workers import Task, install_stream_router  # noqa: E402

APP_NAME = "SEED Vault"


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("seed-vault")
    except Exception:
        return ""


class MainWindow(QMainWindow):
    PAGES = (("🌎", "Main Flows"), ("🚀", "Run from Parameters"), ("🛢️", "DB Explorer"), ("⚙️", "Settings"))

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {_version()}".strip())
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Page navigation as a compact tab bar along the top.
        self.nav = QTabBar()
        self.nav.setDocumentMode(True)
        self.nav.setExpanding(False)
        self.nav.setDrawBase(False)
        self.nav.setStyleSheet("QTabBar::tab { padding: 6px 16px; font-size: 13px; }"
                               "QTabBar::tab:selected { font-weight: bold; }")
        for icon, name in self.PAGES:
            self.nav.addTab(f"{icon}  {name}")
        lay.addWidget(self.nav)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        lay.addWidget(line)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # Pages are created lazily on first visit (keeps start-up fast).
        self._factories = [self._make_workflow, self._make_run_config, self._make_db, self._make_settings]
        self._pages = [None] * len(self._factories)
        for _ in self._factories:
            self.stack.addWidget(QWidget())
        self.nav.currentChanged.connect(self._show_page)
        self._show_page(0)
        self.statusBar().showMessage("Ready")
        self._restore_geometry()

    # page factories -----------------------------------------------------
    def _make_workflow(self):
        from seed_vault.qt.workflow_page import WorkflowPage
        return WorkflowPage()

    def _make_run_config(self):
        from seed_vault.qt.run_config_page import RunConfigPage
        return RunConfigPage()

    def _make_db(self):
        from seed_vault.qt.db_explorer_page import DbExplorerPage
        return DbExplorerPage()

    def _make_settings(self):
        from seed_vault.qt.settings_page import SettingsPage
        return SettingsPage()

    def _show_page(self, i):
        if i < 0:
            return
        if self._pages[i] is None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                page = self._factories[i]()
            finally:
                QApplication.restoreOverrideCursor()
            placeholder = self.stack.widget(i)
            self.stack.insertWidget(i, page)
            self.stack.removeWidget(placeholder)
            placeholder.deleteLater()
            self._pages[i] = page
        self.stack.setCurrentIndex(i)

    def page(self, i):
        self._show_page(i)
        return self._pages[i]

    # window state -------------------------------------------------------
    def _restore_geometry(self):
        geo = QSettings().value("main/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1440, 900)

    def closeEvent(self, e):
        running = [t for t in Task._live if t.is_running()]
        if running:
            if QMessageBox.question(self, "Quit SEED Vault?",
                                    "A download or task is still running. Quit anyway? "
                                    "(It will be cancelled after the current request.)") != QMessageBox.Yes:
                e.ignore()
                return
            for t in running:
                t.cancel()
        QSettings().setValue("main/geometry", self.saveGeometry())
        wf = self._pages[0]
        if wf is not None and hasattr(wf, "shutdown"):
            wf.shutdown()
        super().closeEvent(e)


def _qt_message_handler(mode, context, message):
    if any(m in message for m in _QUIET_MESSAGES):
        return
    sys.__stderr__.write(message + "\n")


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    qInstallMessageHandler(_qt_message_handler)
    QCoreApplication.setOrganizationName("AuScope")
    QCoreApplication.setApplicationName("SEED Vault")
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    install_stream_router()
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationDisplayName(APP_NAME)
    win = MainWindow()
    win.show()
    rc = app.exec()
    # Delete web views before their profile goes away with the application.
    win.deleteLater()
    del win
    QApplication.processEvents()
    return rc


if __name__ == "__main__":
    sys.exit(main())
