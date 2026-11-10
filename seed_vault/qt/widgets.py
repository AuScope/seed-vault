"""Small reusable widgets: log console, banners, collapsible sections, pandas table model."""
import math
from datetime import datetime, timezone
from typing import Iterable, List, Optional

import pandas as pd
from PySide6.QtCore import (QAbstractTableModel, QDate, QDateTime, QModelIndex, QSortFilterProxyModel,
                            Qt, QTime, QTimeZone, Signal)
from PySide6.QtGui import QColor, QFont, QFontDatabase, QTextCursor
from PySide6.QtWidgets import (QDateTimeEdit, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)


def mono_font(point_size: int = 10) -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPointSize(point_size)
    return f


class LogView(QPlainTextEdit):
    """Terminal-style, append-only log. Handles '\\r' progress lines sensibly."""

    def __init__(self, parent=None, max_lines: int = 20000):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setMaximumBlockCount(max_lines)
        self.setFont(mono_font())
        self.setStyleSheet("QPlainTextEdit { background: #111; color: #e8e8e8; }")
        self._pending_cr = False

    def append_text(self, text: str):
        if not text:
            return
        at_bottom = self.verticalScrollBar().value() >= self.verticalScrollBar().maximum() - 4
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        # tqdm-style carriage returns: overwrite the current line
        parts = text.split("\r")
        for i, part in enumerate(parts):
            if i > 0 or self._pending_cr:
                if part or i == len(parts) - 1:
                    cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                    cursor.removeSelectedText()
                self._pending_cr = False
            cursor.insertText(part)
        self._pending_cr = text.endswith("\r")
        if at_bottom:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def clear_log(self):
        self.clear()
        self._pending_cr = False


class Banner(QFrame):
    """Inline info / success / warning / error message with a close button."""
    STYLES = {
        "info": ("#e8f1fb", "#1c4f80"),
        "success": ("#e6f4ea", "#1e6b34"),
        "warning": ("#fff6e0", "#7a5200"),
        "error": ("#fdecea", "#8a1c1c"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 6, 6)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.label.setOpenExternalLinks(True)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.clicked.connect(self.hide)
        lay.addWidget(self.label, 1)
        lay.addWidget(close, 0, Qt.AlignTop)
        self.hide()

    def show_message(self, text: str, kind: str = "info"):
        bg, fg = self.STYLES.get(kind, self.STYLES["info"])
        self.setStyleSheet(f"Banner {{ background: {bg}; border: 1px solid {fg}; border-radius: 4px; }}"
                           f"QLabel {{ color: {fg}; }}")
        self.label.setText(text)
        self.show()

    def info(self, t): self.show_message(t, "info")
    def success(self, t): self.show_message(t, "success")
    def warning(self, t): self.show_message(t, "warning")
    def error(self, t): self.show_message(t, "error")


class Section(QWidget):
    """A titled section that can be collapsed (stand-in for st.expander)."""

    def __init__(self, title: str, parent=None, expanded: bool = True):
        super().__init__(parent)
        self.toggle = QToolButton(text=title, checkable=True, checked=expanded)
        self.toggle.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.toggled.connect(self._on_toggled)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(8, 2, 2, 6)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        lay.addWidget(line)
        lay.addWidget(self.toggle)
        lay.addWidget(self.body)
        self.body.setVisible(expanded)

    def _on_toggled(self, on):
        self.toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(on)

    def addWidget(self, w, *a):
        self.body_layout.addWidget(w, *a)

    def addLayout(self, l, *a):
        self.body_layout.addLayout(l, *a)


def hbox(*widgets, stretch_last=False, margins=0) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(margins, margins, margins, margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    if stretch_last:
        lay.addStretch(1)
    return lay


def button(text: str, slot=None, tooltip: str = None, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if slot:
        b.clicked.connect(slot)
    if tooltip:
        b.setToolTip(tooltip)
    if primary:
        b.setDefault(True)
        b.setStyleSheet("QPushButton { font-weight: bold; }")
    return b


# ----------------------------------------------------------------------------
# UTC datetime edit
# ----------------------------------------------------------------------------
UTC = QTimeZone(b"UTC")


class UtcDateTimeEdit(QDateTimeEdit):
    """A QDateTimeEdit that works in UTC and speaks python datetimes."""

    def __init__(self, parent=None, with_time: bool = True):
        super().__init__(parent)
        self.setTimeZone(UTC)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd HH:mm:ss" if with_time else "yyyy-MM-dd")
        self.setMaximumWidth(190)
        self.setMinimumDateTime(QDateTime(QDate(1800, 1, 1), QTime(0, 0), UTC))
        self.setMaximumDateTime(QDateTime(QDate(2100, 1, 1), QTime(0, 0), UTC))

    def set_py(self, value):
        dt = to_py_datetime(value)
        if dt is None:
            return
        self.setDateTime(QDateTime(QDate(dt.year, dt.month, dt.day),
                                   QTime(dt.hour, dt.minute, dt.second), UTC))

    def py(self) -> datetime:
        q = self.dateTime().toTimeZone(UTC)
        d, t = q.date(), q.time()
        return datetime(d.year(), d.month(), d.day(), t.hour(), t.minute(), t.second())


def to_py_datetime(value) -> Optional[datetime]:
    """Naive-UTC python datetime from datetime/str/UTCDateTime/date."""
    if value is None:
        return None
    if hasattr(value, "datetime") and not isinstance(value, datetime):  # obspy UTCDateTime
        return value.datetime
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    try:  # datetime.date
        return datetime(value.year, value.month, value.day)
    except Exception:
        return None


# ----------------------------------------------------------------------------
# pandas model with a checkbox "selected" column
# ----------------------------------------------------------------------------
class DataFrameModel(QAbstractTableModel):
    """Read-only view of a DataFrame, optionally with a leading check-box column
    bound to a boolean column (``check_col``)."""

    selection_changed = Signal(list)   # list of df index labels whose check state changed

    def __init__(self, df: Optional[pd.DataFrame] = None, check_col: Optional[str] = None,
                 hidden: Iterable[str] = (), headers: Optional[dict] = None,
                 formats: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self._check_col = check_col
        self._hidden = set(hidden)
        self._headers = headers or {}
        self._formats = formats or {}
        self._df = pd.DataFrame()
        self._cols: List[str] = []
        self.set_dataframe(df if df is not None else pd.DataFrame())

    # -- data management -------------------------------------------------
    def set_dataframe(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df
        if self._check_col and not df.empty and self._check_col not in df.columns:
            df[self._check_col] = False
        self._cols = [c for c in df.columns if c not in self._hidden and c != self._check_col]
        self.endResetModel()

    def dataframe(self) -> pd.DataFrame:
        return self._df

    def _has_check(self) -> bool:
        return bool(self._check_col) and not self._df.empty

    def set_checked(self, labels, value: bool):
        if not self._has_check() or len(labels) == 0:
            return
        self._df.loc[list(labels), self._check_col] = value
        self.refresh_checks()
        self.selection_changed.emit(list(labels))

    def refresh_checks(self):
        if self._has_check() and self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0), [Qt.CheckStateRole])

    # -- Qt model API ----------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._cols) + (1 if self._has_check() else 0)

    def _col_name(self, section: int) -> Optional[str]:
        if self._has_check():
            if section == 0:
                return None
            section -= 1
        return self._cols[section]

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            name = self._col_name(section)
            return "✓" if name is None else self._headers.get(name, name)
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        name = self._col_name(index.column())
        if name is None:  # checkbox column
            if role == Qt.CheckStateRole:
                return Qt.Checked if bool(self._df.iloc[row][self._check_col]) else Qt.Unchecked
            if role == Qt.UserRole:
                return int(bool(self._df.iloc[row][self._check_col]))
            return None
        value = self._df.iloc[row][name]
        if role == Qt.UserRole:  # sort key
            if isinstance(value, float) and math.isnan(value):
                return None
            if isinstance(value, pd.Timestamp):
                return value.value
            return value if isinstance(value, (int, float)) else str(value)
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return self._format(name, value)
        if role == Qt.TextAlignmentRole and isinstance(value, (int, float)):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def _format(self, name, value):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        fmt = self._formats.get(name)
        if fmt:
            try:
                return fmt.format(value) if "{" in fmt else value.strftime(fmt) if hasattr(value, "strftime") else str(value)
            except Exception:
                pass
        if isinstance(value, float):
            return f"{value:.4g}" if abs(value) < 1e5 else f"{value:.0f}"
        return str(value)

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self._col_name(index.column()) is None:
            f |= Qt.ItemIsUserCheckable
        return f

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and self._col_name(index.column()) is None:
            label = self._df.index[index.row()]
            checked = (value == Qt.Checked or value == Qt.Checked.value or value is True)
            self._df.at[label, self._check_col] = checked
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            self.selection_changed.emit([label])
            return True
        return False

    def label_for_row(self, row: int):
        return self._df.index[row]

    def row_for_label(self, label) -> int:
        try:
            return self._df.index.get_loc(label)
        except KeyError:
            return -1


class FilterProxy(QSortFilterProxyModel):
    """Sort on raw values (UserRole) and do a case-insensitive filter across all columns."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(Qt.UserRole)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterKeyColumn(-1)

    def lessThan(self, left, right):
        a, b = left.data(Qt.UserRole), right.data(Qt.UserRole)
        if a is None:
            return b is not None
        if b is None:
            return False
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def color_swatch(hex_color: str, text: str) -> str:
    c = QColor(hex_color)
    return f'<span style="color:{c.name()}">■</span> {text}'
