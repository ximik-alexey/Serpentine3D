"""Objects panel: a tree of all scene objects with visibility checkboxes."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _kind_label(kind: str) -> str:
    """Human label for a SceneObject kind."""
    return {"pointcloud": "Point cloud"}.get(kind, kind.capitalize())


class ObjectsPanel(QWidget):
    """A tree of all scene objects: visibility checkbox, name, kind.

    Grouped objects appear as a parent row with children underneath.
    Bidirectional selection: picking a row selects it in the viewport;
    selecting in the viewport highlights it here.
    """

    def __init__(self, scene, selection=None, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.selection = selection
        self._updating = False

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Object", "Type"])
        self.tree.setSelectionMode(
            QTreeWidget.SelectionMode.NoSelection)
        self.tree.setRootIsDecorated(True)
        self.tree.setFocusPolicy(Qt.NoFocus)
        self._selected_rows: set[int] = set()
        self._anchor_row = None
        self.tree.viewport().installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)

        self.tree.itemChanged.connect(self._on_item_changed)
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
        """Redraw the tree from the scene."""
        self._updating = True
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        from . import theme
        hl = QColor(theme.ACCENT)
        selected_ids = (set(self.selection._ids)
                       if self.selection else set())

        # Group objects by group_id
        ungrouped = []
        groups: dict[str, list] = defaultdict(list)
        for obj in self.scene.all():
            if obj.group_id:
                groups[obj.group_id].append(obj)
            else:
                ungrouped.append(obj)

        # Ungrouped objects: top-level rows
        for obj in ungrouped:
            item = self._make_item(obj, selected_ids, hl)
            self.tree.addTopLevelItem(item)

        # Groups: parent + children
        for members in groups.values():
            all_vis = all(o.visible for o in members)
            parent = QTreeWidgetItem([f"Group  ({len(members)})", ""])
            parent.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            parent.setCheckState(0, Qt.CheckState.Checked
                                if all_vis else Qt.CheckState.Unchecked)
            parent.setData(0, Qt.ItemDataRole.UserRole,
                          [o.id for o in members])
            for obj in members:
                child = self._make_item(obj, selected_ids, hl)
                parent.addChild(child)
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)

        QTimer.singleShot(
            0, lambda: self.tree.verticalScrollBar().setValue(scroll))
        self._updating = False

    def _make_item(self, obj, selected_ids, hl):
        """Create a QTreeWidgetItem for one object with a visibility checkbox."""

        flags = (Qt.ItemIsSelectable | Qt.ItemIsEnabled
                 | Qt.ItemIsUserCheckable)
        item = QTreeWidgetItem([obj.name, _kind_label(obj.kind)])
        item.setFlags(flags)
        item.setCheckState(0, Qt.CheckState.Checked
                          if obj.visible else Qt.CheckState.Unchecked)
        item.setData(0, Qt.ItemDataRole.UserRole, obj.id)
        if obj.id in selected_ids:
            item.setBackground(0, hl)
            item.setBackground(1, hl)
        else:
            c = self.scene.color_of(obj)
            tint = QColor(int(c[0] * 255), int(c[1] * 255),
                         int(c[2] * 255))
            tint.setAlpha(40)
            item.setBackground(0, tint)
            item.setBackground(1, tint)
        return item

    # -- selection ----------------------------------------------------------

    def _refresh_colors(self):
        """Update row backgrounds: selected rows get a highlight."""
        from . import theme
        hl = QColor(theme.ACCENT)
        selected = (set(self.selection._ids)
                    if self.selection else set())
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            self._color_item(top, selected, hl)

    def _color_item(self, item, selected, hl):
        """Recursively color an item and its children."""
        obj_id = item.data(0, Qt.ItemDataRole.UserRole)
        if obj_id is not None and not isinstance(obj_id, list):
            if obj_id in selected:
                item.setBackground(0, hl)
                item.setBackground(1, hl)
            else:
                obj = self.scene.get(obj_id)
                if obj is not None:
                    c = self.scene.color_of(obj)
                    tint = QColor(int(c[0] * 255), int(c[1] * 255),
                                 int(c[2] * 255))
                    tint.setAlpha(40)
                    item.setBackground(0, tint)
                    item.setBackground(1, tint)
        for i in range(item.childCount()):
            self._color_item(item.child(i), selected, hl)

    def _on_select(self):
        """Manual selection changed: push to scene."""
        if self._updating or self.selection is None:
            return
        self._refresh_colors()
        ids = []
        for r in self._selected_rows:
            item = self.tree.topLevelItem(r)
            if item:
                d = item.data(0, Qt.ItemDataRole.UserRole)
                if d is not None and not isinstance(d, list):
                    ids.append(d)
        if ids:
            self.selection.set(ids)

    def _on_scene_select(self):
        """Scene selection changed: update row colors in place."""
        self._refresh_colors()

    def _on_item_changed(self, item, column):
        """Checkbox toggled: update visibility (single, group, or multi)."""
        if self._updating or column != 0:
            return
        self._updating = True
        data = item.data(0, Qt.ItemDataRole.UserRole)
        visible = item.checkState(0) == Qt.CheckState.Checked
        if isinstance(data, list):
            # Group parent: toggle all members
            for oid in data:
                self.scene.update(oid, visible=visible)
            for i in range(item.childCount()):
                item.child(i).setCheckState(
                    0, Qt.CheckState.Checked if visible
                    else Qt.CheckState.Unchecked)
        else:
            # Single object: if part of multi-selection, toggle all
            selected = self.tree.selectedItems()
            if len(selected) > 1:
                for it in selected:
                    d = it.data(0, Qt.ItemDataRole.UserRole)
                    if d is not None and not isinstance(d, list):
                        it.setCheckState(
                            0, Qt.CheckState.Checked if visible
                            else Qt.CheckState.Unchecked)
                        self.scene.update(d, visible=visible)
            else:
                self.scene.update(data, visible=visible)
        self._updating = False

    def eventFilter(self, obj, event):
        """Handle all selection manually (tree is NoSelection)."""
        if obj is not self.tree.viewport():
            return False
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        idx = self.tree.indexAt(event.pos())
        if not idx.isValid():
            return False
        row = idx.row()
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            if self._anchor_row is not None:
                lo, hi = (min(self._anchor_row, row),
                         max(self._anchor_row, row))
                self._selected_rows |= set(range(lo, hi + 1))
        elif mods & Qt.KeyboardModifier.ControlModifier:
            if row in self._selected_rows:
                self._selected_rows.discard(row)
            else:
                self._selected_rows.add(row)
            self._anchor_row = row
        else:
            self._selected_rows = {row}
            self._anchor_row = row
        self._on_select()
        return True
