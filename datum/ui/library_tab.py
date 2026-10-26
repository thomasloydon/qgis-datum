# SPDX-License-Identifier: GPL-2.0-or-later
"""Favourites and recently added layers."""

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QFileDialog, QTabWidget,
    QMessageBox,
)

from . import theme
from .widgets import tool_button
from .search_tab import _kind_icon


class LibraryTab(QWidget):
    def __init__(self, iface, actions, library, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.actions = actions
        self.library = library

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 4)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        fav = QWidget()
        fl = QVBoxLayout(fav)
        fl.setContentsMargins(0, 6, 0, 0)
        self.favs = QListWidget()
        self.favs.setObjectName("Library")
        self.favs.setIconSize(QSize(18, 18))
        self.favs.setSpacing(2)
        fl.addWidget(self.favs, 1)
        fb = QHBoxLayout()
        self.f_add = QPushButton(theme.icon("plus", "#ffffff"), "Add")
        self.f_add.setObjectName("Primary")
        self.f_page = tool_button("external", "Open dataset page")
        self.f_remove = tool_button("trash", "Remove from favourites")
        self.f_export = tool_button("download", "Export favourites to a file")
        self.f_import = tool_button("folder", "Import favourites from a file")
        fb.addWidget(self.f_add, 1)
        for b in (self.f_page, self.f_remove, self.f_export, self.f_import):
            fb.addWidget(b)
        fl.addLayout(fb)
        self.tabs.addTab(fav, theme.icon("star"), "Favourites")

        hist = QWidget()
        hl = QVBoxLayout(hist)
        hl.setContentsMargins(0, 6, 0, 0)
        self.hist = QListWidget()
        self.hist.setObjectName("Library")
        self.hist.setIconSize(QSize(18, 18))
        self.hist.setSpacing(2)
        hl.addWidget(self.hist, 1)
        hb = QHBoxLayout()
        self.h_add = QPushButton(theme.icon("refresh", "#ffffff"), "Add again")
        self.h_add.setObjectName("Primary")
        self.h_clear = QPushButton("Clear history")
        self.h_clear.setObjectName("Ghost")
        hb.addWidget(self.h_add, 1)
        hb.addWidget(self.h_clear)
        hl.addLayout(hb)
        self.tabs.addTab(hist, theme.icon("history"), "Recent")
        lay.addWidget(self.tabs, 1)

        self.favs.itemDoubleClicked.connect(lambda *_: self._add_fav())
        self.f_add.clicked.connect(self._add_fav)
        self.f_page.clicked.connect(self._page)
        self.f_remove.clicked.connect(self._remove)
        self.f_export.clicked.connect(self._export)
        self.f_import.clicked.connect(self._import)
        self.hist.itemDoubleClicked.connect(lambda *_: self._add_hist())
        self.h_add.clicked.connect(self._add_hist)
        self.h_clear.clicked.connect(self._clear)
        self.refresh()

    def refresh(self):
        self.favs.clear()
        for ds in self.library.favorite_datasets():
            best = ds.best_resource()
            it = QListWidgetItem(theme.icon(_kind_icon(best.kind) if best else "link",
                                            theme.source_color(ds.source)),
                                 f"{ds.title}\n{ds.source_label}" + (f" · {ds.organization}" if ds.organization else ""))
            it.setData(Qt.ItemDataRole.UserRole, ds)
            it.setToolTip(ds.description[:400])
            self.favs.addItem(it)
        if not self.favs.count():
            it = QListWidgetItem("No favourites yet.\nStar a search result to keep it here.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.favs.addItem(it)
        self.hist.clear()
        for when, ds, res, name in self.library.history_entries():
            it = QListWidgetItem(theme.icon(_kind_icon(res.kind), theme.KIND_COLORS.get(res.kind, "#888")),
                                 f"{name or ds.title}\n{when} · {ds.source_label} · {res.label}")
            it.setData(Qt.ItemDataRole.UserRole, (ds, res))
            self.hist.addItem(it)
        if not self.hist.count():
            it = QListWidgetItem("Layers you add show up here.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.hist.addItem(it)

    def _current_fav(self):
        it = self.favs.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _add_fav(self):
        ds = self._current_fav()
        if ds:
            self.actions.add(ds)

    def _page(self):
        ds = self._current_fav()
        if ds:
            self.actions.open_page(ds)

    def _remove(self):
        row = self.favs.currentRow()
        if row >= 0 and self._current_fav():
            self.library.remove_favorite(row)
            self.refresh()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export favourites", "datum-favourites.json", "JSON (*.json)")
        if path:
            self.library.export_favorites(path)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import favourites", "", "JSON (*.json)")
        if path:
            try:
                n = self.library.import_favorites(path)
            except (OSError, ValueError) as e:
                QMessageBox.warning(self, "Datum", f"Couldn't import: {e}")
                return
            self.refresh()
            self.iface.messageBar().pushInfo("Datum", f"Imported {n} favourite{'s' if n != 1 else ''}.")

    def _add_hist(self):
        it = self.hist.currentItem()
        data = it.data(Qt.ItemDataRole.UserRole) if it else None
        if data:
            ds, res = data
            self.actions.add(ds, res)

    def _clear(self):
        self.library.clear_history()
        self.refresh()
