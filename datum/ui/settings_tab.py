# SPDX-License-Identifier: GPL-2.0-or-later
"""Preferences: sources, how layers are added, downloads, elevation and imagery defaults."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QSpinBox, QComboBox, QCheckBox, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QScrollArea, QFrame, QMessageBox, QInputDialog,
)
from qgis.gui import QgsFileWidget

from ..core import settings, net
from ..core.providers import KNOWN_PORTALS, custom_id
from . import theme
from .widgets import hint, tool_button


class SettingsTab(QWidget):
    changed = pyqtSignal()          # registry needs rebuilding

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # ---------------------------------------------------- custom sources
        g = QGroupBox("Extra catalogues")
        gl = QVBoxLayout(g)
        gl.addWidget(hint("Any CKAN portal or STAC API can be searched alongside the built-in sources."))
        self.endpoints = QListWidget()
        self.endpoints.setMaximumHeight(120)
        gl.addWidget(self.endpoints)
        row = QHBoxLayout()
        self.known = QComboBox()
        self.known.addItem("Add a known portal…", None)
        for p in KNOWN_PORTALS:
            self.known.addItem(p["name"], p)
        row.addWidget(self.known, 1)
        self.add_custom = tool_button("plus", "Add a CKAN or STAC URL")
        self.remove_custom = tool_button("trash", "Remove the selected catalogue")
        row.addWidget(self.add_custom)
        row.addWidget(self.remove_custom)
        gl.addLayout(row)
        lay.addWidget(g)

        # ---------------------------------------------------- search
        g = QGroupBox("Search")
        f = QFormLayout(g)
        self.page_size = QSpinBox()
        self.page_size.setRange(5, 100)
        f.addRow("Results per source", self.page_size)
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 300)
        self.timeout.setSuffix(" s")
        f.addRow("Network timeout", self.timeout)
        self.lang = QComboBox()
        self.lang.addItem("English", "en")
        self.lang.addItem("Français", "fr")
        f.addRow("Bilingual portals", self.lang)
        lay.addWidget(g)

        # ---------------------------------------------------- adding layers
        g = QGroupBox("Adding layers")
        f = QFormLayout(g)
        self.group = QLineEdit()
        self.group.setPlaceholderText("(top of the layer tree)")
        f.addRow("Layer group", self.group)
        self.by_source = QCheckBox("Sub-group per source")
        f.addRow("", self.by_source)
        self.zoom = QCheckBox("Zoom to new layers")
        f.addRow("", self.zoom)
        self.meta = QCheckBox("Copy description, licence and attribution into layer metadata")
        f.addRow("", self.meta)
        self.bc_default = QComboBox()
        self.bc_default.addItem("Live features (WFS, loads what's in view)", "wfs")
        self.bc_default.addItem("Map image (WMS, fastest, no attributes)", "wms")
        self.bc_default.addItem("Download features in view to a file", "download")
        f.addRow("Vector services", self.bc_default)
        self.wfs_max = QSpinBox()
        self.wfs_max.setRange(0, 10_000_000)
        self.wfs_max.setSingleStep(1000)
        self.wfs_max.setSpecialValueText("No limit")
        f.addRow("Max features", self.wfs_max)
        lay.addWidget(g)

        # ---------------------------------------------------- downloads
        g = QGroupBox("Downloads")
        f = QFormLayout(g)
        self.folder = QgsFileWidget()
        self.folder.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        f.addRow("Folder", self.folder)
        self.fmt = QComboBox()
        self.fmt.addItem("GeoPackage", "GPKG")
        self.fmt.addItem("GeoJSON", "GeoJSON")
        self.fmt.addItem("Shapefile", "ESRI Shapefile")
        f.addRow("Vector format", self.fmt)
        lay.addWidget(g)

        # ---------------------------------------------------- imagery
        g = QGroupBox("Imagery search (STAC)")
        f = QFormLayout(g)
        self.stac_days = QSpinBox()
        self.stac_days.setRange(1, 3650)
        self.stac_days.setSuffix(" days")
        f.addRow("Default look-back", self.stac_days)
        self.stac_cloud = QSpinBox()
        self.stac_cloud.setRange(0, 100)
        self.stac_cloud.setSuffix(" %")
        f.addRow("Default max cloud", self.stac_cloud)
        self.stac_items = QSpinBox()
        self.stac_items.setRange(1, 500)
        f.addRow("Default max items", self.stac_items)
        lay.addWidget(g)

        row = QHBoxLayout()
        self.clear_cache = QPushButton(theme.icon("refresh"), "Clear cache")
        self.clear_cache.setObjectName("Ghost")
        self.reset = QPushButton("Reset to defaults")
        self.reset.setObjectName("Ghost")
        row.addWidget(self.clear_cache)
        row.addStretch(1)
        row.addWidget(self.reset)
        lay.addLayout(row)
        lay.addStretch(1)

        self.load()
        self._wire()

    # ------------------------------------------------------------------ load / save
    def load(self):
        self._loading = True
        self.page_size.setValue(settings.get("page_size"))
        self.timeout.setValue(settings.get("timeout"))
        self.lang.setCurrentIndex(max(0, self.lang.findData(settings.get("lang"))))
        self.group.setText(settings.get("group_name"))
        self.by_source.setChecked(settings.get("group_by_source"))
        self.zoom.setChecked(settings.get("zoom_to_layer"))
        self.meta.setChecked(settings.get("add_metadata"))
        self.bc_default.setCurrentIndex(max(0, self.bc_default.findData(settings.get("bc_default"))))
        self.wfs_max.setValue(settings.get("wfs_max_features"))
        self.folder.setFilePath(settings.download_dir())
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(settings.get("wfs_download_format"))))
        self.stac_days.setValue(settings.get("stac_days"))
        self.stac_cloud.setValue(settings.get("stac_max_cloud"))
        self.stac_items.setValue(settings.get("stac_max_items"))
        self._load_endpoints()
        self._loading = False

    def _load_endpoints(self):
        self.endpoints.clear()
        for ep in settings.get("custom_endpoints"):
            it = QListWidgetItem(theme.icon("database"), f"{ep['name']}  ·  {ep.get('type', 'ckan').upper()}")
            it.setToolTip(ep["url"])
            it.setData(Qt.ItemDataRole.UserRole, ep)
            self.endpoints.addItem(it)

    def _wire(self):
        simple = [
            (self.page_size.valueChanged, "page_size", lambda: self.page_size.value()),
            (self.group.editingFinished, "group_name", lambda: self.group.text().strip()),
            (self.by_source.toggled, "group_by_source", lambda: self.by_source.isChecked()),
            (self.zoom.toggled, "zoom_to_layer", lambda: self.zoom.isChecked()),
            (self.meta.toggled, "add_metadata", lambda: self.meta.isChecked()),
            (self.bc_default.currentIndexChanged, "bc_default", lambda: self.bc_default.currentData()),
            (self.wfs_max.valueChanged, "wfs_max_features", lambda: self.wfs_max.value()),
            (self.folder.fileChanged, "download_dir", lambda: self.folder.filePath()),
            (self.fmt.currentIndexChanged, "wfs_download_format", lambda: self.fmt.currentData()),
            (self.stac_days.valueChanged, "stac_days", lambda: self.stac_days.value()),
            (self.stac_cloud.valueChanged, "stac_max_cloud", lambda: self.stac_cloud.value()),
            (self.stac_items.valueChanged, "stac_max_items", lambda: self.stac_items.value()),
        ]
        for signal, key, getter in simple:
            signal.connect(lambda *_, k=key, g=getter: not self._loading and settings.set(k, g()))
        self.timeout.valueChanged.connect(self._timeout_changed)
        self.lang.currentIndexChanged.connect(self._lang_changed)
        self.known.activated.connect(self._add_known)
        self.add_custom.clicked.connect(self._add_url)
        self.remove_custom.clicked.connect(self._remove)
        self.clear_cache.clicked.connect(self._clear_cache)
        self.reset.clicked.connect(self._reset)

    def _timeout_changed(self, v):
        if not self._loading:
            settings.set("timeout", v)
            net.set_timeout(v)

    def _lang_changed(self):
        if not self._loading:
            settings.set("lang", self.lang.currentData())
            self.changed.emit()

    # ------------------------------------------------------------------ endpoints
    def add_endpoint(self, ep):
        eps = settings.get("custom_endpoints")
        if not any(e["url"].rstrip("/") == ep["url"].rstrip("/") for e in eps):
            eps.append(ep)
            settings.set("custom_endpoints", eps)
        enabled = settings.get("enabled_providers")
        pid = custom_id(ep["name"])
        if pid not in enabled:
            settings.set("enabled_providers", enabled + [pid])
        self._load_endpoints()
        self.changed.emit()

    def _add_known(self, idx):
        ep = self.known.itemData(idx)
        self.known.setCurrentIndex(0)
        if ep:
            self.add_endpoint(dict(ep))

    def _add_url(self):
        url, ok = QInputDialog.getText(self, "Add catalogue", "CKAN portal or STAC API URL:")
        if not ok or not url.strip():
            return
        url = url.strip().rstrip("/")
        kinds = ["CKAN portal", "STAC API"]
        kind, ok = QInputDialog.getItem(self, "Add catalogue", "Type:", kinds, 1 if "stac" in url.lower() else 0,
                                        False)
        if not ok:
            return
        name, ok = QInputDialog.getText(self, "Add catalogue", "Name:", text=url.split("//")[-1].split("/")[0])
        if ok and name.strip():
            self.add_endpoint({"name": name.strip(), "url": url, "type": "stac" if kind == "STAC API" else "ckan"})

    def _remove(self):
        it = self.endpoints.currentItem()
        if not it:
            return
        ep = it.data(Qt.ItemDataRole.UserRole)
        settings.set("custom_endpoints", [e for e in settings.get("custom_endpoints") if e["url"] != ep["url"]])
        self._load_endpoints()
        self.changed.emit()

    def _clear_cache(self):
        net.cache.clear()
        self.iface.messageBar().pushInfo("Datum", "Cache cleared.")

    def _reset(self):
        if QMessageBox.question(self, "Datum", "Reset all Datum settings? Favourites and history are kept.") \
                != QMessageBox.StandardButton.Yes:
            return
        settings.reset()
        self.load()
        self.changed.emit()
