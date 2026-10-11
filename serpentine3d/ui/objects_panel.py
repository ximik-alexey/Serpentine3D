"""Objects panel: a paginated list of everything in the viewport."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_ITEMS_PER_PAGE = 20


def _kind_label(kind: str) -> str:
    """Human label for a SceneObject kind."""
    return {"pointcloud": "Point cloud"}.get(kind, kind.capitalize())


class ObjectsPanel(QWidget):
    """A paginated list of all scene objects: name, kind, visibility.

    Bidirectional selection: picking a row selects it in the viewport;
    selecting in the viewport jumps to the right page and highlights.
    Uses QListWidget (not QTreeWidget) to avoid shiboken's
    'already deleted' crash on QTreeWidgetItem.
    Rapid scene notifications are coalesced via a zero-timer.
    """

    def __init__(self, scene, selection=None, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.selection = selection
        self._page = 0
        self._updating = False

        self.list = QListWidget()
        self.list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)

        # Pagination controls
        self._prev_btn = QPushButton("‹")
        self._next_btn = QPushButton("›")
        self._prev_btn.setFixedWidth(28)
        self._next_btn.setFixedWidth(28)
        self._prev_btn.clicked.connect(self._prev_page)
        self._next_btn.clicked.connect(self._next_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._prev_btn)
        row.addStretch()
        row.addWidget(self._next_btn)
        layout.addLayout(row)

        self.list.itemSelectionChanged.connect(self._on_select)
        scene.add_listener(self._on_notify, kinds=("objects",))
        if selection is not None:
            selection.add_listener(self._on_scene_select)
        self.rebuild()

    # -- debounced notification -------------------------------------------

    def _on_notify(self):
        """Scene changed: schedule a rebuild on the next event loop tick."""
        if not self._timer_active():
            self._schedule_rebuild()

    def _timer_active(self) -> bool:
        return self._timer.isActive() if hasattr(self, '_timer') else False

    def _schedule_rebuild(self):
        if not hasattr(self, '_timer'):
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(0)
            self._timer.timeout.connect(self.rebuild)
        self._timer.start()

    # -- pagination ---------------------------------------------------------

    def _total_pages(self) -> int:
        n = len(self.scene.all())
        return max(1, (n + _ITEMS_PER_PAGE - 1) // _ITEMS_PER_PAGE)

    def _page_of(self, obj_id: str) -> int:
        """Which page contains this object id, or 0."""
        for i, o in enumerate(self.scene.all()):
            if o.id == obj_id:
                return i // _ITEMS_PER_PAGE
        return 0

    def _prev_page(self):
        if self._page > 0:
            self._page -= 1
            self.rebuild()

    def _next_page(self):
        if self._page < self._total_pages() - 1:
            self._page += 1
            self.rebuild()

    # -- population ---------------------------------------------------------

    def rebuild(self):
        """Redraw the list from the scene, showing the current page."""
        self._updating = True
        self.list.clear()

        objs = self.scene.all()
        page = self._page
        lo = page * _ITEMS_PER_PAGE
        hi = lo + _ITEMS_PER_PAGE
        selected_ids = (set(self.selection._ids)
                       if self.selection else set())
        for obj in objs[lo:hi]:
            vis = "✓ " if obj.visible else "  "
            text = f"{vis}{obj.name}  [{_kind_label(obj.kind)}]"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, obj.id)
            c = self.scene.color_of(obj)
            tint = QColor(int(c[0] * 255), int(c[1] * 255),
                          int(c[2] * 255))
            tint.setAlpha(40)
            item.setBackground(tint)
            if obj.id in selected_ids:
                item.setSelected(True)
            self.list.addItem(item)

        # page indicator
        label = QListWidgetItem(
            f"  — page {page + 1} / {self._total_pages()} —")
        label.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list.addItem(label)

        self._prev_btn.setEnabled(page > 0)
        self._next_btn.setEnabled(page < self._total_pages() - 1)
        self._updating = False

    # -- selection ----------------------------------------------------------

    def _on_select(self):
        """User picked rows in the list: select them in the scene."""
        if self._updating or self.selection is None:
            return
        items = self.list.selectedItems()
        ids = [it.data(Qt.ItemDataRole.UserRole)
               for it in items
               if it.data(Qt.ItemDataRole.UserRole)]
        if ids:
            self.selection.set(ids)

    def _on_scene_select(self):
        """Scene selection changed: jump to the right page, highlight."""
        if self.selection is None:
            return
        ids = self.selection._ids
        if ids:
            target = self._page_of(ids[0])
            if target != self._page:
                self._page = target
        self.rebuild()
