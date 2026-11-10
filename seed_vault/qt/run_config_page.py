"""Run a workflow directly from a text config (``config_direct.cfg``).

Qt port of ``seed_vault.ui.components.run_from_config.RunFromConfigComponent``.
"""
import html
import os
import tempfile

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QLabel, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget

from seed_vault.qt.widgets import Banner, LogView, button, hbox, mono_font
from seed_vault.qt.workers import run_task_with_stop
from seed_vault.service.seismoloader import run_main
from seed_vault.service.settings_store import (DIRECT_CONFIG_PATH, default_settings, render_config,
                                               validate_config_file)
from seed_vault.utils.constants import DOC_BASE_URL


class RunConfigPage(QWidget):
    def __init__(self, parent=None, config_path: str = DIRECT_CONFIG_PATH):
        super().__init__(parent)
        self.path = config_path
        self._task = None
        self._saved_text = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(QLabel("Set the search parameters directly and run your workflow in one go. "
                             "Edits are validated when saved."))
        self.banner = Banner()
        lay.addWidget(self.banner)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.save_btn = button("Save", self.save, "Save and validate (Ctrl+S)")
        self.save_btn.setShortcut("Ctrl+S")
        self.revert_btn = button("Revert", self.load, "Discard unsaved edits")
        self.reset_btn = button("Reset to defaults", self.reset_defaults)
        self.import_btn = button("Open…", self.open_file, "Load parameters from another .cfg file")
        self.export_btn = button("Save as…", self.save_as)
        help_btn = button("Help", lambda: QDesktopServices.openUrl(
            QUrl(f"{DOC_BASE_URL}/flows/run_from_parameters.html#parameter-reference")))
        ll.addLayout(hbox(self.save_btn, self.revert_btn, self.reset_btn, self.import_btn, self.export_btn,
                          None, help_btn))
        self.editor = QPlainTextEdit()
        self.editor.setFont(mono_font())
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.textChanged.connect(self._on_text_changed)
        ll.addWidget(self.editor, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.run_btn = button("▶  Run", self.run, primary=True)
        self.cancel_btn = button("Cancel", self.cancel)
        self.cancel_btn.setEnabled(False)
        self.dirty_label = QLabel()
        self.dirty_label.setStyleSheet("color: #a15c00;")
        rl.addLayout(hbox(self.run_btn, self.cancel_btn, self.dirty_label, None,
                          button("Clear log", lambda: self.log.clear_log())))
        self.log = LogView()
        rl.addWidget(self.log, 1)
        split.addWidget(right)
        split.setSizes([600, 600])
        lay.addWidget(split, 1)
        self.load()

    # ------------------------------------------------------------------
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self._saved_text = f.read()
        except FileNotFoundError:
            self._saved_text = render_config(default_settings())
        self.editor.setPlainText(self._saved_text)
        self._validate()

    def _on_text_changed(self):
        dirty = self.editor.toPlainText() != self._saved_text
        self.dirty_label.setText("Unsaved changes – Run uses the saved file" if dirty else "")

    def _validate(self) -> bool:
        try:
            errors, warnings = validate_config_file(self.path)
        except Exception as e:  # noqa: BLE001
            self.banner.error(f"Could not parse configuration: {html.escape(str(e))}")
            return False
        if errors:
            self.banner.error(f"<pre>{html.escape(errors)}</pre><b>Please resolve the errors before running.</b>")
        elif warnings:
            self.banner.warning(f"<pre>{html.escape(warnings)}</pre>")
        else:
            self.banner.hide()
        return not errors

    def _write(self, text: str, path: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def save(self):
        text = self.editor.toPlainText()
        # validate a temp copy first so a broken edit never replaces a working file silently
        with tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False, encoding="utf-8") as tmp:
            tmp.write(text)
        try:
            errors, _ = validate_config_file(tmp.name)
        except Exception as e:  # noqa: BLE001
            errors = str(e)
        finally:
            os.unlink(tmp.name)
        self._write(text, self.path)
        self._saved_text = text
        self._on_text_changed()
        if self._validate():
            self.banner.success("Configuration saved." if not errors else "Configuration saved with errors.")

    def reset_defaults(self):
        self.editor.setPlainText(render_config(default_settings()))
        self.save()

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open config", "", "Config (*.cfg);;All files (*)")
        if path:
            with open(path, encoding="utf-8") as f:
                self.editor.setPlainText(f.read())
            self.banner.info(f"Loaded {os.path.basename(path)} – click Save to use it.")

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save config as", "config.cfg", "Config (*.cfg)")
        if path:
            self._write(self.editor.toPlainText(), path)
            self.banner.success(f"Saved a copy to {path}")

    # ------------------------------------------------------------------
    def _set_running(self, running: bool):
        self.run_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        for w in (self.editor, self.save_btn, self.revert_btn, self.reset_btn, self.import_btn):
            w.setEnabled(not running)

    def run(self):
        if self._task is not None:
            return
        if self.editor.toPlainText() != self._saved_text:
            self.save()
        if not self._validate():
            return
        self.log.append_text("Starting config processing…\n")
        self._set_running(True)
        self.banner.info("Running… progress appears in the log.")
        self._task = run_task_with_stop(
            lambda stop: run_main(settings=None, from_file=self.path, stop_event=stop),
            on_log=self.log.append_text, on_success=self._on_result,
            on_error=lambda m: self.banner.error(f"Processing encountered errors: {html.escape(m)}"),
            on_done=self._on_done)

    def cancel(self):
        if self._task is not None:
            self._task.cancel()
            self.cancel_btn.setEnabled(False)
            self.banner.warning("Cancelling… (finishing the current request)")

    def _on_result(self, result):
        if self._task is not None and self._task.stop_event.is_set():
            self.banner.warning("Processing was cancelled by user.")
        elif result:
            self.banner.success("Processing completed successfully!")
        else:
            self.banner.warning("Processing finished without results. Check the log for details.")

    def _on_done(self):
        self._task = None
        self._set_running(False)
