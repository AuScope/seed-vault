"""Application settings: storage paths, DB sync, credentials, custom FDSN clients.

Qt port of ``seed_vault.ui.components.settings.SettingsComponent``.
"""
import html
import os
import re
from typing import List, Optional

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDateEdit, QFileDialog, QFormLayout, QHeaderView, QLabel, QLineEdit,
                               QPlainTextEdit, QSpinBox, QStyledItemDelegate, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from seed_vault.enums.common import ClientType
from seed_vault.service.fdsn_client import DISABLED, SERVICES, build_client, service_mappings_from_row
from seed_vault.models.config import AuthConfig
from seed_vault.qt.widgets import Banner, LogView, button, hbox, mono_font
from seed_vault.qt.workers import run_task
from seed_vault.service.db import populate_database_from_sds
from seed_vault.service.settings_store import (APP_SECTIONS, default_settings, load_settings, save_sections,
                                               save_settings)
from seed_vault.utils.constants import DOC_BASE_URL

CLIENT_KEYS = [
    ("client", "Short name shown in the client lists (letters, digits, '_' or '-')"),
    ("url", "Base URL of the server, e.g. https://example.org. Optional if service URLs are given."),
    ("dataselect", "Full waveform (dataselect) service URL, e.g. https://example.org/fdsnws/dataselect/1. "
                   "Blank = standard path under the base URL; 'none' = not offered."),
    ("event", "Full event service URL, e.g. https://example.org/custom/event/1. "
              "Blank = standard path under the base URL; 'none' = not offered."),
    ("station", "Full station service URL. Blank = standard path under the base URL; 'none' = not offered."),
]
CLIENT_COLUMNS = list(zip(["Client name", "Base URL", "Dataselect URL", "Event URL", "Station URL"],
                          [t for _, t in CLIENT_KEYS]))

LICENSE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "LICENSE")


class _PasswordDelegate(QStyledItemDelegate):
    def displayText(self, value, locale):
        return "•" * len(str(value)) if value else ""

    def createEditor(self, parent, option, index):
        e = QLineEdit(parent)
        e.setEchoMode(QLineEdit.Password)
        return e


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = None
        self._sync_task = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.save_btn = button("Save settings", self.save, primary=True)
        lay.addLayout(hbox(QLabel("<h2>Settings</h2>"), None, self.save_btn,
                           button("Reload", self.reload, "Discard unsaved changes"),
                           button("Reset to defaults", self.reset_defaults),
                           button("Help", lambda: QDesktopServices.openUrl(QUrl(f"{DOC_BASE_URL}/app_settings.html")))))
        self.banner = Banner()
        lay.addWidget(self.banner)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)
        tabs.addTab(self._build_data_tab(), "🛠️ Data")
        tabs.addTab(self._build_auth_tab(), "🔑 Credentials")
        tabs.addTab(self._build_clients_tab(), "📡 Clients")
        tabs.addTab(self._build_license_tab(), "📜 License")
        self.reload()

    # ------------------------------------------------------------------
    def _path_row(self, edit: QLineEdit, is_dir: bool):
        def browse():
            if is_dir:
                p = QFileDialog.getExistingDirectory(self, "Choose folder", edit.text() or os.getcwd())
            else:
                p, _ = QFileDialog.getSaveFileName(self, "Choose database file", edit.text() or "database.sqlite",
                                                   "SQLite (*.sqlite *.db);;All files (*)",
                                                   options=QFileDialog.DontConfirmOverwrite)
            if p:
                edit.setText(p)
        return hbox(edit, button("Browse…", browse))

    def _build_data_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()
        self.db_path = QLineEdit()
        self.db_path.setToolTip("Full path to your database, e.g. /archive/database.sqlite")
        self.sds_path = QLineEdit()
        self.sds_path.setToolTip("Root path of your SDS archive. If you change this you may have to resync "
                                 "the database.")
        f.addRow("Database path:", self._path_row(self.db_path, False))
        f.addRow('Local archive (<a href="https://www.seiscomp.de/seiscomp3/doc/applications/slarchive/SDS.html">'
                 'SDS</a>):', self._path_row(self.sds_path, True))
        for i in range(f.rowCount()):
            lbl = f.itemAt(i, QFormLayout.LabelRole)
            if lbl and isinstance(lbl.widget(), QLabel):
                lbl.widget().setOpenExternalLinks(True)
        self.num_proc = QSpinBox()
        self.num_proc.setRange(0, 512)
        self.num_proc.setToolTip("0 = use all available CPUs")
        self.gap_tol = QSpinBox()
        self.gap_tol.setRange(0, 10 ** 7)
        self.gap_tol.setSuffix(" s")
        self.num_proc.setMaximumWidth(90)
        self.gap_tol.setMaximumWidth(130)
        f.addRow("Number of processes:", hbox(self.num_proc, None))
        f.addRow("Gap tolerance:", hbox(self.gap_tol, None))
        lay.addLayout(f)

        lay.addWidget(QLabel("<h3>Sync database with existing archive</h3>"
                             "Scan the SDS archive and record what data is available locally."))
        g = QFormLayout()
        self.patterns = QLineEdit("??.*.*.?H?.D.202?.???")
        self.patterns.setToolTip("Comma-separated glob patterns for SDS file names")
        g.addRow("Search patterns:", self.patterns)
        self.since_enabled = QCheckBox("Only files modified since")
        self.since = QDateEdit(QDate.currentDate().addMonths(-1))
        self.since.setCalendarPopup(True)
        self.since.setEnabled(False)
        self.since_enabled.toggled.connect(self.since.setEnabled)
        g.addRow(self.since_enabled, self.since)
        lay.addLayout(g)
        self.sync_btn = button("Sync database", self.sync_db, "Saves settings, then scans the archive")
        lay.addLayout(hbox(self.sync_btn, None))
        self.sync_log = LogView()
        lay.addWidget(self.sync_log, 1)
        return w

    def _build_auth_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Credentials for restricted / embargoed data. Use the 2-character network code, "
                             "or NN.STA if authentication is per station. Passwords are stored in the local "
                             "config file."))
        self.auth_table = QTableWidget(0, 3)
        self.auth_table.setHorizontalHeaderLabels(["Network code", "Username", "Password"])
        self.auth_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.auth_table.setItemDelegateForColumn(2, _PasswordDelegate(self.auth_table))
        lay.addWidget(self.auth_table, 1)
        lay.addLayout(hbox(button("Add credential", lambda: self._add_row(self.auth_table, ["XX", "user", ""], edit=True)),
                           button("Delete selected", lambda: self._delete_rows(self.auth_table)), None))
        return w

    def _build_clients_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        intro = QLabel(
            "<b>Extra clients</b> – add your own FDSN servers. Give a <b>base URL</b> for a standard server "
            "(services at <code>&lt;base&gt;/fdsnws/&lt;service&gt;/1</code>). To use non-standard addresses, "
            "fill in any of the <b>Dataselect / Event / Station</b> columns with the full service URL, e.g. "
            "<code>https://example.org/custom/event/1</code>. Leave a service blank to use the standard path, "
            "or enter <code>none</code> if the server doesn't offer it. The base URL is optional when service "
            "URLs are given.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.client_table = QTableWidget(0, len(CLIENT_COLUMNS))
        self.client_table.setHorizontalHeaderLabels([h for h, _ in CLIENT_COLUMNS])
        hdr = self.client_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Stretch)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for c, (_, tip) in enumerate(CLIENT_COLUMNS):
            self.client_table.horizontalHeaderItem(c).setToolTip(tip)
        lay.addWidget(self.client_table, 1)
        self.test_btn = button("Test selected", self.test_client,
                               "Check which services the highlighted client responds to (uses the values in the "
                               "table, before saving)")
        lay.addLayout(hbox(button("Add client", lambda: self._add_row(self.client_table, ["MYCLIENT", "https://", "", "", ""],
                                                                    edit=True)),
                           button("Delete selected", lambda: self._delete_rows(self.client_table)),
                           self.test_btn, None))
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        self.test_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.test_result)
        lay.addWidget(QLabel("<b>Built-in clients (via ObsPy)</b>"))
        self.orig_clients = QTableWidget(0, 2)
        self.orig_clients.setHorizontalHeaderLabels(["Client name", "URL"])
        self.orig_clients.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.orig_clients.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.orig_clients, 1)
        return w

    def _build_license_tab(self):
        t = QPlainTextEdit()
        t.setReadOnly(True)
        t.setFont(mono_font())
        try:
            with open(LICENSE_FILE, encoding="utf-8") as f:
                t.setPlainText(f.read())
        except OSError:
            t.setPlainText("CSIRO Open Source Software License Agreement (variation of the BSD/MIT License).\n"
                           "See the LICENSE file distributed with SEED Vault.")
        return t

    @staticmethod
    def _add_row(table, values, edit=False):
        r = table.rowCount()
        table.insertRow(r)
        for c, v in enumerate(values):
            table.setItem(r, c, QTableWidgetItem(v))
        if edit:
            table.setCurrentCell(r, 0)
            table.editItem(table.item(r, 0))

    @staticmethod
    def _delete_rows(table):
        for r in sorted({i.row() for i in table.selectedIndexes()}, reverse=True):
            table.removeRow(r)

    @staticmethod
    def _rows(table):
        out = []
        for r in range(table.rowCount()):
            out.append([(table.item(r, c).text().strip() if table.item(r, c) else "")
                        for c in range(table.columnCount())])
        return out

    # ------------------------------------------------------------------
    def reload(self):
        try:
            self.settings = load_settings(empty_geo=False)
        except Exception as e:  # noqa: BLE001
            self.banner.error(f"Could not read settings ({html.escape(str(e))}). Use <b>Reset to defaults</b>.")
            return
        s = self.settings
        self.db_path.setText(s.db_path)
        self.sds_path.setText(s.sds_path)
        self.num_proc.setValue(int(s.processing.num_processes or 0))
        self.gap_tol.setValue(int(s.processing.gap_tolerance or 0))
        self.auth_table.setRowCount(0)
        for a in s.auths or []:
            self._add_row(self.auth_table, [a.nslc_code, a.username, a.password])
        self.client_table.setRowCount(0)
        for c in s.client_url_mapping.get_extra_client_details():
            self._add_row(self.client_table, [c["client"], c["url"], c["dataselect"], c["event"], c["station"]])
        self.orig_clients.setRowCount(0)
        for k, v in s.client_url_mapping.get_clients(client_type=ClientType.ORIGINAL).items():
            self._add_row(self.orig_clients, [k, v])
        self.banner.hide()

    def _collect(self) -> bool:
        s = self.settings
        s.db_path = self.db_path.text().strip()
        s.sds_path = self.sds_path.text().strip()
        s.processing.num_processes = self.num_proc.value()
        s.processing.gap_tolerance = self.gap_tol.value()
        auths = {}
        for code, user, pw in self._rows(self.auth_table):
            if code:
                auths[code] = AuthConfig(nslc_code=code, username=user, password=pw)  # later wins
        s.auths = list(auths.values())
        return True

    def _client_rows(self) -> List[dict]:
        keys = [k for k, _ in CLIENT_KEYS]
        return [dict(zip(keys, row)) for row in self._rows(self.client_table)]

    def _validate_clients(self, clients: List[dict]) -> Optional[str]:
        builtin = {k.upper() for k in self.settings.client_url_mapping.get_clients(client_type=ClientType.ORIGINAL)}
        seen = set()
        for c in clients:
            name = c["client"]
            if not name:
                return "Every extra client needs a name."
            if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
                return f"Client name '{html.escape(name)}' may only contain letters, digits, '_' and '-'."
            if name.upper() in builtin:
                return f"'{html.escape(name)}' is already a built-in client; please choose another name."
            if name.upper() in seen:
                return f"Client '{html.escape(name)}' is listed twice."
            seen.add(name.upper())
            services = {k: c[k] for k in SERVICES if c[k]}
            if not c["url"] and not any(v.lower() != DISABLED for v in services.values()):
                return f"Client '{html.escape(name)}' needs a base URL or at least one service URL."
            for label, value in [("base URL", c["url"])] + list(services.items()):
                if value and value.lower() != DISABLED and not re.match(r"https?://[^/\s]+", value):
                    return (f"Client '{html.escape(name)}': {label} must start with http:// or https:// "
                            f"(or be 'none' for a service).")
        return None

    def test_client(self):
        rows = sorted({i.row() for i in self.client_table.selectedIndexes()})
        if not rows:
            self.test_result.setText("Highlight a client row first.")
            return
        c = self._client_rows()[rows[0]]
        err = self._validate_clients([c]) if c["client"] else "Give the client a name first."
        if err:
            self.test_result.setText(f'<span style="color:#b00020">{err}</span>')
            return
        self.test_btn.setEnabled(False)
        self.test_result.setText(f"Testing {html.escape(c['client'])}…")

        def probe():
            mappings = service_mappings_from_row(c)
            client = build_client(c["url"], mappings, timeout=30)
            out = {}
            for svc in SERVICES:
                if svc in mappings and mappings[svc] is None:
                    out[svc] = (False, None)          # marked 'none' by the user
                else:
                    out[svc] = (svc in client.services, client._build_url(svc, "query"))
            return out

        def ok(result):
            lines = []
            for svc, (available, url) in result.items():
                mark = "✅" if available else "❌"
                where = "not offered" if url is None else f"<code>{html.escape(url)}</code>"
                lines.append(f"{mark} <b>{svc}</b>: {where}")
            self.test_result.setText(f"<b>{html.escape(c['client'])}</b><br>" + "<br>".join(lines))

        run_task(probe, on_success=ok, capture_output=False,
                 on_error=lambda m: self.test_result.setText(
                     f'<span style="color:#b00020">Could not reach {html.escape(c["client"])}: '
                     f'{html.escape(m)}</span>'),
                 on_done=lambda: self.test_btn.setEnabled(True))

    def save(self):
        clients = self._client_rows()
        err = self._validate_clients(clients)
        if err:
            self.banner.error(err)
            return False
        try:
            self._collect()
            save_sections(self.settings, APP_SECTIONS)
            self.settings.client_url_mapping.save(clients)
        except Exception as e:  # noqa: BLE001
            self.banner.error(f"Could not save settings: {html.escape(str(e))}")
            return False
        self.banner.success("Settings saved.")
        return True

    def reset_defaults(self):
        save_settings(default_settings())
        self.reload()
        self.banner.success("Settings have been reset to default.")

    def sync_db(self):
        if self._sync_task is not None or not self.save():
            return
        patterns = [p.strip() for p in self.patterns.text().split(",") if p.strip()]
        newer = self.since.date().toPython() if self.since_enabled.isChecked() else None
        s = self.settings
        self.sync_btn.setEnabled(False)
        self.sync_log.append_text(f"Syncing {s.sds_path} → {s.db_path}\n")
        self._sync_task = run_task(
            populate_database_from_sds, sds_path=s.sds_path, db_path=s.db_path, search_patterns=patterns,
            newer_than=newer, num_processes=s.processing.num_processes,
            gap_tolerance=s.processing.gap_tolerance,
            on_log=self.sync_log.append_text,
            on_success=lambda _: self.banner.success("Database sync complete."),
            on_error=lambda m: self.banner.error(f"Sync failed: {html.escape(m)}"),
            on_done=self._sync_done)

    def _sync_done(self):
        self._sync_task = None
        self.sync_btn.setEnabled(True)
