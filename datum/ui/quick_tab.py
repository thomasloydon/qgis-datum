# SPDX-License-Identifier: GPL-2.0-or-later
"""One-click catalogue of verified layers grouped by theme."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QTreeWidget, QTreeWidgetItem, QPushButton, QToolButton,
    QCheckBox, QHeaderView, QButtonGroup,
)

from ..core import loader
from ..core.catalog import ENTRIES, CATEGORY_ORDER, CATEGORY_ICONS
from ..core.models import Kind, bbox_intersects
from . import theme
from .widgets import hint

COVERAGES = ["All", "BC", "Canada", "USA", "Global"]
# entries worth showing when someone is working in a region
USABLE_IN = {"BC": {"BC", "Canada", "Global"}, "Canada": {"BC", "Canada", "Global"},
             "USA": {"USA", "Global"}, "Global": {"Global"}}


class QuickTab(QWidget):
    def __init__(self, iface, actions, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.actions = actions

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(6)
        root.addWidget(hint("Verified layers that just work. Tick several and add them in one go, "
                            "or double-click one."))
        self.filter = QLineEdit()
        self.filter.setObjectName("DatumSearch")
        self.filter.setPlaceholderText("Filter quick picks…")
        self.filter.setClearButtonEnabled(True)
        self.filter.addAction(theme.icon("filter", theme.muted()), QLineEdit.ActionPosition.LeadingPosition)
        root.addWidget(self.filter)

        crow = QHBoxLayout()
        crow.setSpacing(4)
        self.cov_group = QButtonGroup(self)
        self.cov_group.setExclusive(True)
        for i, c in enumerate(COVERAGES):
            b = QToolButton()
            b.setObjectName("Chip")
            b.setText(c)
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.cov_group.addButton(b, i)
            crow.addWidget(b)
        crow.addStretch(1)
        self.in_view = QToolButton()
        self.in_view.setObjectName("Chip")
        self.in_view.setCheckable(True)
        self.in_view.setText("In view")
        self.in_view.setIcon(theme.icon("extent"))
        self.in_view.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.in_view.setToolTip("Hide layers that don't cover the current map extent")
        crow.addWidget(self.in_view)
        root.addLayout(crow)

        self.tree = QTreeWidget()
        self.tree.setObjectName("Catalog")
        self.tree.setHeaderLabels(["Layer", "Area", "Type"])
        self.tree.setIndentation(14)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(True)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.tree, 1)

        self.download = QCheckBox("Download vector layers in view instead of streaming")
        self.download.setToolTip("Saves WFS layers clipped to the map extent as local files")
        root.addWidget(self.download)
        brow = QHBoxLayout()
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("Ghost")
        self.add_btn = QPushButton(theme.icon("plus", "#ffffff"), "Add selected")
        self.add_btn.setObjectName("Primary")
        brow.addWidget(self.clear_btn)
        brow.addWidget(self.add_btn, 1)
        root.addLayout(brow)

        self._populate()
        self.filter.textChanged.connect(self._apply_filter)
        self.cov_group.idClicked.connect(lambda *_: self._apply_filter())
        self.in_view.toggled.connect(lambda *_: self._apply_filter())
        self.tree.itemChanged.connect(lambda *_: self._update_count())
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.add_btn.clicked.connect(self.add_checked)
        self.clear_btn.clicked.connect(self._clear)
        if iface:
            iface.mapCanvas().extentsChanged.connect(lambda: self.in_view.isChecked() and self._apply_filter())
        self._update_count()

    def _populate(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        cats = {}
        for cat in CATEGORY_ORDER:
            top = QTreeWidgetItem([cat])
            top.setIcon(0, theme.accent_icon(CATEGORY_ICONS.get(cat, "layers")))
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            top.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(top)
            cats[cat] = top
        for ds in ENTRIES:
            parent = cats.get(ds.category)
            if parent is None:
                continue
            kind = ds.resources[0].kind if ds.resources else Kind.LINK
            it = QTreeWidgetItem([ds.title, ds.extra.get("coverage", ""), Kind.LABELS.get(kind, kind)])
            licence = f"<br><i>{ds.license}</i>" if ds.license else ""
            it.setToolTip(0, f"<b>{ds.title}</b><br>{ds.description}{licence}")
            it.setData(0, Qt.ItemDataRole.UserRole, ds)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Unchecked)
            it.setForeground(1, theme.muted())
            it.setForeground(2, QColor(theme.KIND_COLORS.get(kind, "#888")))
            parent.addChild(it)
        for top in cats.values():
            top.setText(0, f"{top.text(0)}  ({top.childCount()})")
        self.tree.expandItem(cats[CATEGORY_ORDER[0]])
        self.tree.blockSignals(False)

    def _iter_children(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top, top.child(j)

    def _apply_filter(self):
        text = self.filter.text().lower().strip()
        cov = COVERAGES[self.cov_group.checkedId()] if self.cov_group.checkedId() >= 0 else "All"
        view = loader.canvas_bbox_ll() if self.in_view.isChecked() else None
        visible_per_top = {}
        for top, it in self._iter_children():
            ds = it.data(0, Qt.ItemDataRole.UserRole)
            hay = f"{ds.title} {ds.description} {' '.join(ds.tags)}".lower()
            ok = (not text or all(w in hay for w in text.split()))
            ok = ok and (cov == "All" or ds.extra.get("coverage") in USABLE_IN[cov])
            ok = ok and (view is None or bbox_intersects(ds.bbox, view))
            it.setHidden(not ok)
            visible_per_top[id(top)] = visible_per_top.get(id(top), 0) + (1 if ok else 0)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            n = visible_per_top.get(id(top), 0)
            top.setHidden(n == 0)
            if text:
                top.setExpanded(True)

    def _checked(self):
        return [it.data(0, Qt.ItemDataRole.UserRole) for _, it in self._iter_children()
                if it.checkState(0) == Qt.CheckState.Checked and not it.isHidden()]

    def _update_count(self):
        n = len(self._checked())
        self.add_btn.setText(f"Add {n} layer{'s' if n != 1 else ''}" if n else "Add selected")
        self.add_btn.setEnabled(n > 0)

    def _clear(self):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self._update_count()

    def _double_clicked(self, item, col):
        ds = item.data(0, Qt.ItemDataRole.UserRole)
        if ds is not None:
            self.actions.add(ds, download=self.download.isChecked())

    def add_checked(self):
        chosen = self._checked()
        # basemaps first so they land underneath
        chosen.sort(key=lambda d: 0 if d.resources and d.resources[0].kind == Kind.XYZ else 1)
        for ds in chosen:
            self.actions.add(ds, download=self.download.isChecked())
        self._clear()
