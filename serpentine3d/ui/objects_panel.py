"""Objects panel: a paginated list of everything in the viewport."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

_ITEMS_PER_PAGE = 20
def _kind_label(kind: str) -> str:
    """Human label for a SceneObject kind."""
    return {"pointcloud": "Point cloud"}.get(kind, kind.capitalize())


class ObjectsPanel(QWidget):
    """A paginated tree of all scene objects: name, kind, visibility.

    Mirrors LayersPanel: subscribes to scene notifications and rebuilds
    its tree on change. Adds page navigation (prev/next + indicator)
    so a large scene does not require scrolling through hundreds of rows.
    """

    changed = Signal()

    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._page = 0

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Name", "Kind", ""])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)

        # Pagination controls
        self._prev_btn = QPushButton("‹")
        self._next_btn = QPushButton("›")
        self._page_label = QTreeWidgetItem(["", "", ""])
        self._page_label.setFlags(Qt.ItemFlag.NoItemFlags)

        self._prev_btn.setFixedWidth(28)
        self._next_btn.setFixedWidth(28)
        self._prev_btn.clicked.connect(self._prev_page)
        self._next_btn.clicked.connect(self._next_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.tree)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._prev_btn)
        row.addStretch()
        row.addWidget(self._next_btn)
        layout.addLayout(row)

        self.tree.itemSelectionChanged.connect(self._on_select)
        scene.add_listener(self.rebuild, kinds=("objects",))
        self.rebuild()

    # -- pagination ---------------------------------------------------------

    def _total_pages(self) -> int:
        n = len(self.scene.all())
        return max(1, (n + _ITEMS_PER_PAGE - 1) // _ITEMS_PER_PAGE)

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
        """Redraw the tree from the scene, showing the current page."""
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()

        objs = self.scene.all()
        page = self._page
        lo = page * _ITEMS_PER_PAGE
        hi = lo + _ITEMS_PER_PAGE
        for obj in objs[lo:hi]:
            item = QTreeWidgetItem([
                obj.name,
                _kind_label(obj.kind),
                "✓" if obj.visible else "",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, obj.id)
            c = self.scene.color_of(obj)
            from PySide6.QtGui import QColor
            tint = QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255))
            tint.setAlpha(60)
            item.setBackground(0, tint)
            self.tree.addTopLevelItem(item)

        # page indicator row
        self.tree.addTopLevelItem(self._page_label)
        self._page_label.setText(1, f"{page + 1} / {self._total_pages()}")
        self._prev_btn.setEnabled(page > 0)
        self._next_btn.setEnabled(page < self._total_pages() - 1)

        self.tree.setUpdatesEnabled(True)

    # -- selection ----------------------------------------------------------

    def _on_select(self):
        items = self.tree.selectedItems()
        ids = [it.data(0, Qt.ItemDataRole.UserRole)
               for it in items
               if it.data(0, Qt.ItemDataRole.UserRole)]
        if ids:
            self.changed.emit()
