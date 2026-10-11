"""Objects panel: a list of everything in the viewport."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _kind_label(kind: str) -> str:
    """Human label for a SceneObject kind."""
    return {"pointcloud": "Point cloud"}.get(kind, kind.capitalize())


class ObjectsPanel(QWidget):
    """A scrollable list of all scene objects: name, kind, visibility.

    Bidirectional selection: picking a row selects it in the viewport;
    selecting in the viewport highlights it here.
    """

    def __init__(self, scene, selection=None, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.selection = selection
        self._updating = False

        self.list = QListWidget()
        self.list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)

        self.list.itemSelectionChanged.connect(self._on_select)
        scene.add_listener(self._on_notify, kinds=("objects",))
        if selection is not None:
            selection.add_listener(self._on_scene_select)
        self.rebuild()

    # -- debounced notification -------------------------------------------

    def _on_notify(self):
        if not hasattr(self, '_timer'):
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(0)
            self._timer.timeout.connect(self.rebuild)
        self._timer.start()

    # -- population ---------------------------------------------------------

    def rebuild(self):
        """Redraw the list from the scene."""
        self._updating = True
        self.list.clear()
        selected_ids = (set(self.selection._ids)
                       if self.selection else set())
        for obj in self.scene.all():
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
        self._updating = False

    # -- selection ----------------------------------------------------------

    def _refresh_colors(self):
        """Update row backgrounds: selected rows get a highlight."""
        from . import theme
        hl = QColor(theme.ACCENT)
        for i in range(self.list.count()):
            item = self.list.item(i)
            obj_id = item.data(Qt.ItemDataRole.UserRole)
            if obj_id is None:
                continue
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            if item.isSelected():
                item.setBackground(hl)
            else:
                c = self.scene.color_of(obj)
                tint = QColor(int(c[0] * 255), int(c[1] * 255),
                             int(c[2] * 255))
                tint.setAlpha(40)
                item.setBackground(tint)

    def _on_select(self):
        """User picked rows in the list: select them in the scene."""
        if self._updating or self.selection is None:
            return
        self._refresh_colors()
        items = self.list.selectedItems()
        ids = [it.data(Qt.ItemDataRole.UserRole)
               for it in items
               if it.data(Qt.ItemDataRole.UserRole)]
        if ids:
            self.selection.set(ids)

    def _on_scene_select(self):
        """Scene selection changed: highlight here."""
        if self.selection is None:
            return
        self.rebuild()
