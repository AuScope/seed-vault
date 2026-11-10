"""SQLite explorer for the local archive database.

Qt port of ``seed_vault.ui.components.data_explorer.DataExplorerComponent``.
"""
import html
import time

from PySide6.QtCore import QRegularExpression, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QSyntaxHighlighter, QTextCharFormat, QColor
from PySide6.QtWidgets import (QCheckBox, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter,
                               QTableView, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from seed_vault.qt.widgets import Banner, DataFrameModel, FilterProxy, button, hbox, mono_font
from seed_vault.qt.workers import run_task
from seed_vault.service.db import DatabaseManager
from seed_vault.service.settings_store import load_settings

EXAMPLES = [
    "SELECT * FROM archive_data LIMIT 100",
    "SELECT * FROM arrival_data LIMIT 100",
    "SELECT DISTINCT network, station FROM archive_data",
    "SELECT network, station, COUNT(*) AS n FROM archive_data GROUP BY network, station ORDER BY n DESC",
    'DELETE FROM archive_data WHERE network="IU" AND station="DAV"',
]
MAX_ROWS_SHOWN = 200_000
KEYWORDS = ("select from where and or not insert into values update set delete create drop alter table "
            "index view join left right inner outer on group by order having limit offset distinct as "
            "count sum avg min max like in is null between case when then else end union all pragma").split()


class SqlHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        kw = QTextCharFormat()
        kw.setForeground(QColor("#0b57d0"))
        kw.setFontWeight(QFont.Bold)
        st = QTextCharFormat()
        st.setForeground(QColor("#b3261e"))
        cm = QTextCharFormat()
        cm.setForeground(QColor("#777"))
        num = QTextCharFormat()
        num.setForeground(QColor("#006c4c"))
        self.rules = [(QRegularExpression(r"\b(" + "|".join(KEYWORDS) + r")\b",
                                          QRegularExpression.CaseInsensitiveOption), kw),
                      (QRegularExpression(r"\b\d+(\.\d+)?\b"), num),
                      (QRegularExpression(r"'[^']*'|\"[^\"]*\""), st),
                      (QRegularExpression(r"--[^\n]*"), cm)]

    def highlightBlock(self, text):
        for rx, fmt in self.rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


def _match_pk(v):
    return {None: "", 0: "", 1: "Primary key", 2: "Foreign key"}.get(v, "Other")


class DbExplorerPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db: DatabaseManager = None
        self.db_path = None
        self._task = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        docs = button("Documentation", lambda: QDesktopServices.openUrl(
            QUrl("https://auscope.github.io/seed-vault/app_db_explorer.html")))
        lay.addLayout(hbox(self.path_label, None, button("Reload database", self.reload), docs))

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        # -- query tab
        q = QWidget()
        ql = QVBoxLayout(q)
        ql.setContentsMargins(0, 4, 0, 0)
        split = QSplitter(Qt.Vertical)
        self.editor = QPlainTextEdit("SELECT * FROM archive_data LIMIT 10")
        self.editor.setFont(mono_font(11))
        SqlHighlighter(self.editor.document())
        split.addWidget(self.editor)
        res = QWidget()
        rl = QVBoxLayout(res)
        rl.setContentsMargins(0, 0, 0, 0)
        self.exec_btn = button("▶  Execute (Ctrl+Enter)", self.execute, primary=True)
        self.exec_btn.setShortcut("Ctrl+Return")
        self.status = QLabel()
        self.export_btn = button("Export CSV…", self.export_csv)
        rl.addLayout(hbox(self.exec_btn, self.status, None, self.export_btn))
        self.banner = Banner()
        rl.addWidget(self.banner)
        self.model = DataFrameModel()
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        self.result_view = QTableView()
        self.result_view.setModel(self.proxy)
        self.result_view.setSortingEnabled(True)
        self.result_view.setAlternatingRowColors(True)
        self.result_view.verticalHeader().setDefaultSectionSize(20)
        rl.addWidget(self.result_view, 1)
        split.addWidget(res)
        split.setSizes([150, 500])
        ql.addWidget(split)
        self.tabs.addTab(q, "Execute SQL")

        # -- history
        self.history = QListWidget()
        self.history.setFont(mono_font())
        self.history.itemDoubleClicked.connect(lambda it: self._load_query(it.data(Qt.UserRole)))
        h = QWidget()
        hl = QVBoxLayout(h)
        hl.addWidget(QLabel("Double-click a query to load it into the editor."))
        hl.addWidget(self.history)
        self.tabs.addTab(h, "Query history")

        # -- schema
        s = QWidget()
        sl = QVBoxLayout(s)
        self.show_types = QCheckBox("Show types")
        self.show_types.setChecked(True)
        self.show_types.toggled.connect(self.refresh_schema)
        self.schema = QTreeWidget()
        self.schema.setHeaderLabels(["Table / column", "Type", "Key"])
        sl.addWidget(self.show_types)
        sl.addWidget(self.schema)
        self.tabs.addTab(s, "DB schema")

        # -- examples
        ex = QListWidget()
        ex.setFont(mono_font())
        for e in EXAMPLES:
            it = QListWidgetItem(e)
            it.setData(Qt.UserRole, e)
            ex.addItem(it)
        ex.itemDoubleClicked.connect(lambda it: self._load_query(it.data(Qt.UserRole)))
        e = QWidget()
        el = QVBoxLayout(e)
        el.addWidget(QLabel("Double-click an example to load it into the editor. "
                            "<b>DELETE / UPDATE statements modify your database.</b>"))
        el.addWidget(ex)
        self.tabs.addTab(e, "Example queries")

    # ------------------------------------------------------------------
    def reload(self):
        try:
            path = load_settings().db_path
        except Exception as e:  # noqa: BLE001
            self.banner.error(f"Could not read settings: {e}")
            return
        self.db_path = path
        self.db = DatabaseManager(path)
        self.path_label.setText(f"Database: <code>{html.escape(path)}</code>")
        self.refresh_schema()

    def showEvent(self, e):
        super().showEvent(e)
        if self.db is None:
            self.reload()

    def refresh_schema(self, *_):
        self.schema.clear()
        if self.db is None:
            return
        show_types = self.show_types.isChecked()
        try:
            with self.db.connection() as conn:
                cur = conn.cursor()
                for (table,) in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                    t = QTreeWidgetItem([table])
                    for row in conn.cursor().execute(f"PRAGMA table_info('{table}')"):
                        t.addChild(QTreeWidgetItem([row[1], row[2].upper() if show_types else "",
                                                    _match_pk(row[5])]))
                    self.schema.addTopLevelItem(t)
                    t.setExpanded(True)
            self.schema.resizeColumnToContents(0)
        except Exception as e:  # noqa: BLE001
            self.banner.error(f"Could not read schema: {e}")

    def _load_query(self, q):
        self.editor.setPlainText(q)
        self.tabs.setCurrentIndex(0)

    def execute(self):
        if self._task is not None or self.db is None:
            return
        query = self.editor.textCursor().selectedText().replace(" ", "\n").strip() or \
            self.editor.toPlainText().strip()
        if not query:
            return
        first = query.split()[0].upper()
        if first in ("DELETE", "DROP", "UPDATE", "ALTER", "TRUNCATE"):
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(self, "Modify database?",
                                    f"This {first} statement will modify your database. Continue?") \
                    != QMessageBox.Yes:
                return
        self.banner.hide()
        self.status.setText("Running…")
        self.exec_btn.setEnabled(False)
        t0 = time.perf_counter()

        def ok(result):
            has_error, message, df = result
            ms = int((time.perf_counter() - t0) * 1000)
            self.status.setText(f"{ms} ms · {time.strftime('%X')}")
            (self.banner.error if has_error else self.banner.success)(html.escape(message))
            if df is not None:
                if df.columns.has_duplicates:
                    df.columns = _dedupe(df.columns)
                if len(df) > MAX_ROWS_SHOWN:
                    self.banner.warning(f"{html.escape(message)} Showing the first {MAX_ROWS_SHOWN:,} rows.")
                    df = df.head(MAX_ROWS_SHOWN)
                self.model.set_dataframe(df)
                self.result_view.resizeColumnsToContents()
            self._add_history(query, ms, message)
            if not has_error and query.split()[0].upper() in ("CREATE", "DROP", "ALTER"):
                self.refresh_schema()

        self._task = run_task(self.db.execute_query, query, on_success=ok,
                              on_error=lambda m: self.banner.error(html.escape(m)),
                              on_done=self._done, capture_output=False)

    def _done(self):
        self._task = None
        self.exec_btn.setEnabled(True)

    def _add_history(self, query, ms, message):
        if self.history.count() and self.history.item(0).data(Qt.UserRole) == query:
            return
        it = QListWidgetItem(f"[{time.strftime('%X')}] {ms} ms – {message}\n{query}")
        it.setData(Qt.UserRole, query)
        self.history.insertItem(0, it)
        while self.history.count() > 50:
            self.history.takeItem(self.history.count() - 1)

    def export_csv(self):
        df = self.model.dataframe()
        if df is None or df.empty:
            return self.banner.warning("Run a SELECT query first.")
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "query.csv", "CSV (*.csv)")
        if path:
            df.to_csv(path, index=False)
            self.banner.success(f"Exported {len(df)} rows to {html.escape(path)}")


def _dedupe(cols):
    seen, out = {}, []
    for c in cols:
        seen[c] = seen.get(c, 0) + 1
        out.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
    return out
