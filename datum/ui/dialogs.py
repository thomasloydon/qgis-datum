# SPDX-License-Identifier: GPL-2.0-or-later
"""Dialogs: pick layers from a service, and browse STAC items over an area."""


from qgis.PyQt.QtCore import Qt, QDate
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QDialogButtonBox,
    QComboBox, QCheckBox, QSpinBox, QDateEdit, QTreeWidget, QTreeWidgetItem, QPushButton, QProgressBar,
    QFormLayout, QHeaderView, QAbstractItemView,
)

from ..core import tasks, settings
from . import theme
from .widgets import AoiPicker, hint, section


class LayerPickerDialog(QDialog):
    """Pick one or more layers from a parsed capabilities document / ArcGIS service."""

    def __init__(self, title, layers, parent=None, multi=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(460, 480)
        self.layers = layers
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{len(layers)}</b> layers available. Tick the ones to add."))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter layers…")
        self.filter.setClearButtonEnabled(True)
        lay.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        for i, l in enumerate(layers):
            text = l["title"] if l["title"] == l["name"] else f"{l['title']}  —  {l['name']}"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setToolTip(l.get("abstract") or l["name"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if len(layers) == 1 else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        lay.addWidget(self.list, 1)
        self.list.itemDoubleClicked.connect(self._toggle)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Add layers")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.filter.textChanged.connect(self._filter)

    def _toggle(self, it):
        it.setCheckState(Qt.CheckState.Unchecked if it.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)

    def _filter(self, text):
        t = text.lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def selected(self):
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(self.layers[it.data(Qt.ItemDataRole.UserRole)])
        return out


class StacDialog(QDialog):
    """Search a STAC collection over an area and add the chosen assets."""

    def __init__(self, iface, provider, collection, title, parent=None, preset=None, on_add=None):
        super().__init__(parent)
        self.iface = iface
        self.provider = provider
        self.collection = collection
        self.items = []
        self.on_add = on_add
        self.preset = preset
        self.setWindowTitle(f"{title} — find imagery")
        self.setMinimumSize(560, 620)
        self.setStyleSheet(theme.stylesheet())

        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{title}</b><br><span>{provider.label} · collection <code>{collection}</code></span>")
        head.setWordWrap(True)
        lay.addWidget(head)

        lay.addWidget(section("Where"))
        self.aoi = AoiPicker(iface, self, show_buffer=False)
        lay.addWidget(self.aoi)

        lay.addWidget(section("When & filters"))
        form = QFormLayout()
        drow = QHBoxLayout()
        self.use_dates = QCheckBox("Between")
        self.start = QDateEdit(QDate.currentDate().addDays(-settings.get("stac_days")))
        self.end = QDateEdit(QDate.currentDate())
        for d in (self.start, self.end):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
        drow.addWidget(self.use_dates)
        drow.addWidget(self.start)
        drow.addWidget(QLabel("and"))
        drow.addWidget(self.end)
        drow.addStretch(1)
        form.addRow("Dates", drow)
        crow = QHBoxLayout()
        self.use_cloud = QCheckBox("At most")
        self.cloud = QSpinBox()
        self.cloud.setRange(0, 100)
        self.cloud.setSuffix(" % cloud")
        self.cloud.setValue(settings.get("stac_max_cloud"))
        crow.addWidget(self.use_cloud)
        crow.addWidget(self.cloud)
        crow.addStretch(1)
        form.addRow("Cloud", crow)
        self.max_items = QSpinBox()
        self.max_items.setRange(1, 500)
        self.max_items.setValue(settings.get("stac_max_items"))
        form.addRow("Max results", self.max_items)
        lay.addLayout(form)
        optical = preset == "sentinel2" or "sentinel-2" in collection or "landsat" in collection
        self.use_dates.setChecked(optical)
        self.use_cloud.setChecked(optical)

        srow = QHBoxLayout()
        self.search_btn = QPushButton(theme.icon("search", "#ffffff"), "Search")
        self.search_btn.setObjectName("Primary")
        srow.addWidget(self.search_btn)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        srow.addWidget(self.status, 1)
        lay.addLayout(srow)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item", "Date", "Cloud"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tree, 1)

        lay.addWidget(section("Add"))
        arow = QFormLayout()
        self.asset = QComboBox()
        arow.addRow("Asset / band", self.asset)
        self.mosaic = QCheckBox("Mosaic selected items into one layer")
        self.mosaic.setChecked(True)
        arow.addRow("", self.mosaic)
        self.download = QCheckBox("Download, clipped to the area (keeps working offline)")
        arow.addRow("", self.download)
        lay.addLayout(arow)
        if provider.signer:
            lay.addWidget(hint("Planetary Computer links expire after about an hour. Tick Download to keep the data."))

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.add_btn = QPushButton(theme.icon("plus", "#ffffff"), "Add to map")
        self.add_btn.setObjectName("Primary")
        self.add_btn.setEnabled(False)
        bb.addButton(self.add_btn, QDialogButtonBox.ButtonRole.ActionRole)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.search_btn.clicked.connect(self.search)
        self.add_btn.clicked.connect(self.add)
        self.tree.itemSelectionChanged.connect(
            lambda: self.add_btn.setEnabled(bool(self.tree.selectedItems()) and self.asset.count() > 0))

    def search(self):
        bbox = self.aoi.bbox_ll()
        if not bbox:
            self.status.setText("Pick an area first.")
            return
        datetime = None
        if self.use_dates.isChecked():
            datetime = f"{self.start.date().toString('yyyy-MM-dd')}T00:00:00Z/" \
                       f"{self.end.date().toString('yyyy-MM-dd')}T23:59:59Z"
        cloud = self.cloud.value() if self.use_cloud.isChecked() else None
        limit = self.max_items.value()
        self.progress.setVisible(True)
        self.search_btn.setEnabled(False)
        self.status.setText("Searching…")

        def work(task):
            return self.provider.search_items(self.collection, bbox, datetime=datetime, max_cloud=cloud, limit=limit)

        tasks.run(f"Datum: searching {self.collection}", work, self._found, silent=True)

    def _found(self, ok, items, error):
        self.progress.setVisible(False)
        self.search_btn.setEnabled(True)
        if error or not ok:
            self.status.setText(f"Search failed: {error}" if error else "Canceled.")
            return
        items = sorted(items or [], key=lambda i: i.get("properties", {}).get("datetime") or "", reverse=True)
        self.items = items
        self.tree.clear()
        keys = []
        for i, it in enumerate(items):
            p = it.get("properties", {})
            cc = p.get("eo:cloud_cover")
            row = QTreeWidgetItem([it.get("id", ""), (p.get("datetime") or p.get("start_datetime") or "")[:10],
                                   f"{cc:.0f}%" if isinstance(cc, (int, float)) else "–"])
            row.setData(0, Qt.ItemDataRole.UserRole, i)
            self.tree.addTopLevelItem(row)
            for k in self.provider.raster_assets(it):
                if k not in keys:
                    keys.append(k)
        prev = self.asset.currentText()
        self.asset.clear()
        preferred = ["visual", "dtm", "dem", "data", "elevation", "dsm", "rendered_preview"]
        keys.sort(key=lambda k: (preferred.index(k) if k in preferred else 99, k))
        for k in keys:
            title = next((it["assets"][k].get("title") for it in items if k in it.get("assets", {})), "") or k
            self.asset.addItem(f"{k}  —  {title}" if title != k else k, k)
        if prev:
            idx = self.asset.findText(prev)
            if idx >= 0:
                self.asset.setCurrentIndex(idx)
        self.status.setText(f"{len(items)} item{'s' if len(items) != 1 else ''} found."
                            if items else "Nothing found. Try a wider date range or a different area.")
        if items:
            self.tree.topLevelItem(0).setSelected(True)

    def add(self):
        key = self.asset.currentData()
        chosen = [self.items[r.data(0, Qt.ItemDataRole.UserRole)] for r in self.tree.selectedItems()]
        if not chosen or not key:
            return
        if self.on_add:
            self.on_add(self.provider, self.collection, chosen, key, self.mosaic.isChecked(),
                        self.download.isChecked(), self.aoi.bbox_ll())
