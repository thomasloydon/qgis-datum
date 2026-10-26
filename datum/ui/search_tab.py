# SPDX-License-Identifier: GPL-2.0-or-later
"""Search every enabled catalogue at once and preview / add results."""

import html

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices
try:
    from qgis.PyQt.QtWidgets import QAction
except ImportError:  # Qt6
    from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QToolButton, QComboBox, QLabel, QListView, QSplitter,
    QFrame, QTextBrowser, QTreeWidget, QTreeWidgetItem, QPushButton, QMenu, QHeaderView, QAbstractItemView,
    QProgressBar,
)

from ..core import settings, tasks, loader
from ..core.models import Kind, SearchQuery, bbox_intersects
from . import theme
from .widgets import ResultModel, ResultDelegate, DATASET_ROLE, tool_button, hint

FORMAT_FILTERS = [
    ("Any format", []),
    ("Live vector (WFS, ArcGIS)", [Kind.WFS, Kind.ARCGIS_FEATURE]),
    ("Map images (WMS, tiles)", [Kind.WMS, Kind.WMTS, Kind.XYZ, Kind.ARCGIS_MAP]),
    ("Rasters, DEMs & imagery", [Kind.COG, Kind.STAC_COLLECTION, Kind.DEM, Kind.RASTER_FILE, Kind.ARCGIS_IMAGE]),
    ("Downloadable files", [Kind.VECTOR_FILE, Kind.COG, Kind.RASTER_FILE]),
]

SORTS = [("Best match", "relevance"), ("Recently updated", "updated"), ("Title A–Z", "title")]

SUGGESTIONS = ["dem", "lidar", "streams", "roads", "parcels", "wildfire", "forest cover", "watersheds",
               "land cover", "sentinel-2", "geology", "parks"]


class SearchTab(QWidget):
    def __init__(self, iface, actions, get_registry, library, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.actions = actions
        self.get_registry = get_registry
        self.library = library
        self.search_id = 0
        self.pending = 0
        self.pages = {}         # provider id -> last SearchPage
        self.totals = {}
        self.errors = {}
        self.query = None
        self.current = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(6)

        # search box
        row = QHBoxLayout()
        self.box = QLineEdit()
        self.box.setObjectName("DatumSearch")
        self.box.setPlaceholderText("Search open data — e.g. lidar, streams, parcels, wildfire…")
        self.box.setClearButtonEnabled(True)
        self.box.addAction(theme.icon("search", theme.muted()), QLineEdit.ActionPosition.LeadingPosition)
        row.addWidget(self.box, 1)
        self.go = QPushButton("Search")
        self.go.setObjectName("Primary")
        row.addWidget(self.go)
        root.addLayout(row)

        # filters
        frow = QHBoxLayout()
        frow.setSpacing(4)
        self.sources_btn = QToolButton()
        self.sources_btn.setObjectName("Ghost")
        self.sources_btn.setIcon(theme.icon("database"))
        self.sources_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.sources_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sources_menu = QMenu(self)
        self.sources_btn.setMenu(self.sources_menu)
        frow.addWidget(self.sources_btn)
        self.fmt = QComboBox()
        for label, _ in FORMAT_FILTERS:
            self.fmt.addItem(label)
        self.fmt.setToolTip("Only show datasets offering these kinds of resources")
        frow.addWidget(self.fmt, 1)
        self.in_view = QToolButton()
        self.in_view.setObjectName("Chip")
        self.in_view.setCheckable(True)
        self.in_view.setText("In view")
        self.in_view.setIcon(theme.icon("extent"))
        self.in_view.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.in_view.setToolTip("Only datasets overlapping the current map extent "
                                "(where the catalogue records an extent)")
        self.in_view.setChecked(settings.get("filter_to_extent"))
        frow.addWidget(self.in_view)
        root.addLayout(frow)

        frow2 = QHBoxLayout()
        frow2.setSpacing(4)
        self.org = QComboBox()
        self.org.addItem("Any organization", None)
        self.org.setToolTip("Organisations from the catalogue results (CKAN portals)")
        self.org.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.org.setMinimumContentsLength(12)
        frow2.addWidget(self.org, 1)
        self.sort = QComboBox()
        for label, _ in SORTS:
            self.sort.addItem(label)
        frow2.addWidget(self.sort)
        root.addLayout(frow2)

        # status
        srow = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        srow.addWidget(self.status, 1)
        self.spinner = QProgressBar()
        self.spinner.setRange(0, 0)
        self.spinner.setFixedWidth(60)
        self.spinner.setVisible(False)
        srow.addWidget(self.spinner)
        root.addLayout(srow)

        # results + detail
        self.split = QSplitter(Qt.Orientation.Vertical)
        listwrap = QWidget()
        lw = QVBoxLayout(listwrap)
        lw.setContentsMargins(0, 0, 0, 0)
        lw.setSpacing(2)
        self.model = ResultModel(self)
        self.view = QListView()
        self.view.setObjectName("Results")
        self.view.setModel(self.model)
        self.view.setItemDelegate(ResultDelegate(self.model, self.view))
        self.view.setMouseTracking(True)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setUniformItemSizes(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lw.addWidget(self.view, 1)
        self.more = QPushButton("Load more results")
        self.more.setObjectName("Ghost")
        self.more.setVisible(False)
        lw.addWidget(self.more)
        self.empty = self._empty_state()
        lw.addWidget(self.empty)
        self.split.addWidget(listwrap)
        self.detail = self._detail_panel()
        self.split.addWidget(self.detail)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        self.split.setSizes([520, 340])
        self.split.setChildrenCollapsible(False)
        root.addWidget(self.split, 1)
        self.detail.setVisible(False)
        self.view.setVisible(False)

        # wiring
        self.box.returnPressed.connect(self.search)
        self.go.clicked.connect(self.search)
        self.fmt.currentIndexChanged.connect(self._refilter)
        self.sort.currentIndexChanged.connect(self._refilter)
        self.org.activated.connect(lambda *_: self.search())
        self.in_view.toggled.connect(self._in_view_toggled)
        self.more.clicked.connect(self.load_more)
        self.view.selectionModel().currentChanged.connect(lambda cur, prev: self.show_detail(cur))
        self.view.doubleClicked.connect(lambda idx: self.actions.add(idx.data(DATASET_ROLE)))
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.rebuild_sources_menu()

    # ------------------------------------------------------------------ construction helpers
    def _empty_state(self):
        w = QFrame()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 24, 12, 12)
        title = QLabel("Find data without the hunt")
        f = title.font()
        f.setPointSizeF(f.pointSizeF() + 3)
        f.setBold(True)
        title.setFont(f)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        sub = hint("Searches the BC Data Catalogue, Open Government Canada, NRCan's datacube, "
                   "Earth Search and Planetary Computer at once. Double-click a result to add it.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        chips = QWidget()
        grid = QHBoxLayout(chips)
        grid.setContentsMargins(0, 8, 0, 0)
        grid.setSpacing(4)
        flow_rows = [SUGGESTIONS[:6], SUGGESTIONS[6:]]
        box = QVBoxLayout()
        for words in flow_rows:
            r = QHBoxLayout()
            r.addStretch(1)
            for wd in words:
                b = QToolButton()
                b.setObjectName("Chip")
                b.setText(wd)
                b.clicked.connect(lambda _=False, t=wd: (self.box.setText(t), self.search()))
                r.addWidget(b)
            r.addStretch(1)
            box.addLayout(r)
        lay.addLayout(box)
        lay.addStretch(1)
        return w

    def _detail_panel(self):
        w = QFrame()
        w.setObjectName("Detail")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)
        top = QHBoxLayout()
        self.d_title = QLabel()
        self.d_title.setWordWrap(True)
        f = self.d_title.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 1)
        self.d_title.setFont(f)
        self.d_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.d_title, 1)
        self.d_fav = tool_button("star", "Add to favourites")
        self.d_page = tool_button("external", "Open the dataset page in your browser")
        top.addWidget(self.d_fav)
        top.addWidget(self.d_page)
        lay.addLayout(top)
        self.d_meta = QLabel()
        self.d_meta.setObjectName("Hint")
        self.d_meta.setWordWrap(True)
        lay.addWidget(self.d_meta)
        self.d_desc = QTextBrowser()
        self.d_desc.setOpenExternalLinks(True)
        self.d_desc.setFrameShape(QFrame.Shape.NoFrame)
        self.d_desc.setMaximumHeight(90)
        lay.addWidget(self.d_desc)
        self.d_res = QTreeWidget()
        self.d_res.setHeaderLabels(["Resource", "Type"])
        self.d_res.setRootIsDecorated(False)
        self.d_res.setAlternatingRowColors(True)
        self.d_res.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.d_res.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.d_res.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.d_res.setMaximumHeight(130)
        lay.addWidget(self.d_res)
        brow = QHBoxLayout()
        self.d_add = QPushButton(theme.icon("plus", "#ffffff"), "Add to map")
        self.d_add.setObjectName("Primary")
        self.d_add.setToolTip("Add the selected resource (or the best one) to the map")
        self.d_dl = QPushButton(theme.icon("download"), "Download in view")
        self.d_dl.setObjectName("Ghost")
        self.d_dl.setToolTip("Save the features inside the current map extent to a local file")
        self.d_copy = tool_button("copy", "Copy the resource URL")
        brow.addWidget(self.d_add, 1)
        brow.addWidget(self.d_dl)
        brow.addWidget(self.d_copy)
        lay.addLayout(brow)

        self.d_add.clicked.connect(self._add_selected)
        self.d_dl.clicked.connect(lambda: self._add_selected(download=True))
        self.d_copy.clicked.connect(self._copy_selected)
        self.d_fav.clicked.connect(self._toggle_fav)
        self.d_page.clicked.connect(lambda: self.current and self.actions.open_page(self.current))
        self.d_res.itemDoubleClicked.connect(lambda *_: self._add_selected())
        self.d_res.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.d_res.customContextMenuRequested.connect(self._res_menu)
        return w

    # ------------------------------------------------------------------ sources menu
    def rebuild_sources_menu(self):
        self.sources_menu.clear()
        enabled = set(settings.get("enabled_providers"))
        reg = self.get_registry()
        for pid, p in reg.items():
            act = QAction(p.label, self.sources_menu)
            act.setCheckable(True)
            act.setChecked(pid in enabled)
            act.setToolTip(p.description)
            act.setData(pid)
            act.toggled.connect(self._source_toggled)
            self.sources_menu.addAction(act)
        self.sources_menu.setToolTipsVisible(True)
        self._update_sources_label()

    def _source_toggled(self):
        ids = [a.data() for a in self.sources_menu.actions() if a.isChecked()]
        settings.set("enabled_providers", ids)
        self._update_sources_label()

    def active_providers(self):
        reg = self.get_registry()
        ids = [a.data() for a in self.sources_menu.actions() if a.isChecked()]
        return [reg[i] for i in ids if i in reg]

    def _update_sources_label(self):
        n = sum(1 for a in self.sources_menu.actions() if a.isChecked())
        total = len(self.sources_menu.actions())
        self.sources_btn.setText(f"Sources {n}/{total}")

    # ------------------------------------------------------------------ searching
    def _in_view_toggled(self, on):
        settings.set("filter_to_extent", on)
        if self.query is not None:
            self.search()

    def build_query(self, offset=0):
        bbox = loader.canvas_bbox_ll() if self.in_view.isChecked() else None
        return SearchQuery(text=self.box.text().strip(), bbox=bbox,
                           formats=FORMAT_FILTERS[self.fmt.currentIndex()][1],
                           sort=SORTS[self.sort.currentIndex()][1], offset=offset,
                           limit=settings.get("page_size"))

    def search(self):
        self.search_id += 1
        sid = self.search_id
        self.query = self.build_query()
        org = self.org.currentData()
        providers = self.active_providers()
        if org:
            providers = [p for p in providers if p.id == org[0]]
        if not providers:
            self.status.setText("No sources enabled — pick some from the Sources menu.")
            return
        self.model.clear()
        self.model.favorites = {f"{f.get('source')}:{f.get('id')}" for f in self.library.favorites}
        self.pages, self.totals, self.errors = {}, {}, {}
        self.empty.setVisible(False)
        self.view.setVisible(True)
        self.detail.setVisible(False)
        self.more.setVisible(False)
        if not org:
            self._reset_orgs()
        for p in providers:
            q = SearchQuery(**{**self.query.__dict__})
            if org and p.id == org[0]:
                q.organization = org[1]
            self._run(p, q, sid)
        self._update_status()

    def load_more(self):
        sid = self.search_id
        org = self.org.currentData()
        for pid, page in list(self.pages.items()):
            if page.has_more:
                p = self.get_registry().get(pid)
                if p is None:
                    continue
                q = SearchQuery(**{**self.query.__dict__})
                q.offset = page.offset + len(page.datasets)
                if org and pid == org[0]:
                    q.organization = org[1]
                self._run(p, q, sid)
        self.more.setVisible(False)

    def _run(self, provider, query, sid):
        self.pending += 1
        self.spinner.setVisible(True)

        def work(task):
            return provider.search(query)

        def done(ok, page, error):
            self.pending -= 1
            self.spinner.setVisible(self.pending > 0)
            if sid != self.search_id:
                return
            if error or page is None:
                self.errors[provider.id] = str(error or "canceled")
            else:
                self.pages[provider.id] = page
                self.totals[provider.id] = page.total if page.total is not None else len(page.datasets)
                self.model.extend(self._filtered(page.datasets))
                self._merge_facets(provider, page)
            self.more.setVisible(any(p.has_more for p in self.pages.values()))
            self._update_status()
            if self.model.rowCount() and not self.view.currentIndex().isValid():
                self.view.setCurrentIndex(self.model.index(0))

        tasks.run(f"Datum: searching {provider.label}", work, done, silent=True)

    def _filtered(self, datasets):
        kinds = set(FORMAT_FILTERS[self.fmt.currentIndex()][1])
        bbox = self.query.bbox if self.query else None
        out = []
        for d in datasets:
            if kinds and not kinds & set(d.kinds):
                continue
            if bbox and not bbox_intersects(d.bbox, bbox):
                continue
            out.append(d)
        return out

    def _refilter(self):
        if self.query is not None:
            self.search()

    def _update_status(self):
        n = self.model.rowCount()
        total = sum(self.totals.values())
        parts = []
        if self.pending:
            parts.append("Searching…")
        if self.totals:
            sources = len(self.totals)
            parts.append(f"{n:,} shown of {total:,} from {sources} source{'s' if sources != 1 else ''}")
        if self.errors:
            names = ", ".join(self.get_registry()[p].label for p in self.errors if p in self.get_registry())
            parts.append(f"⚠ {names} unavailable")
            self.status.setToolTip("\n".join(f"{k}: {v}" for k, v in self.errors.items()))
        self.status.setText("  ·  ".join(parts))
        if not self.pending and n == 0 and self.query is not None:
            self.status.setText((self.status.text() + "  ·  " if self.status.text() else "") +
                                "No matches. Try fewer words, another format, or turn off “In view”.")

    def _reset_orgs(self):
        self.org.blockSignals(True)
        self.org.clear()
        self.org.addItem("Any organization", None)
        self.org.blockSignals(False)

    def _merge_facets(self, provider, page):
        orgs = page.facets.get("organization") or []
        if not orgs or self.org.currentData():
            return
        short = {"bcdc": "BC", "opencanada": "Canada"}.get(provider.id, provider.label)
        self.org.blockSignals(True)
        for name, label, count in orgs[:40]:
            self.org.addItem(f"{short} · {label} ({count})", (provider.id, name))
        self.org.blockSignals(False)

    # ------------------------------------------------------------------ detail
    def show_detail(self, index):
        ds = index.data(DATASET_ROLE) if index.isValid() else None
        self.current = ds
        self.detail.setVisible(ds is not None)
        if ds is None:
            return
        self.d_title.setText(ds.title)
        bits = [f"<b>{html.escape(ds.source_label)}</b>"]
        for v in (ds.organization, ds.updated, ds.license, ds.extra.get("coverage")):
            if v:
                bits.append(html.escape(str(v)))
        self.d_meta.setText("  ·  ".join(bits))
        desc = html.escape(ds.description or "No description provided.")
        if ds.tags:
            desc += "<br><br>" + " ".join(f"<span style='color:{theme.accent().name()}'>#{html.escape(t)}</span>"
                                          for t in ds.tags[:12])
        self.d_desc.setHtml(f"<div style='font-size:12px'>{desc}</div>")
        self.d_res.clear()
        best = ds.best_resource(self.actions.preferred_kinds(ds))
        for r in ds.resources:
            it = QTreeWidgetItem([r.name, r.label])
            it.setIcon(0, theme.icon(_kind_icon(r.kind), theme.KIND_COLORS.get(r.kind, "#888")))
            it.setToolTip(0, f"{r.url}\n{r.layer}" if r.layer else r.url)
            it.setData(0, Qt.ItemDataRole.UserRole, r)
            if not r.addable:
                it.setForeground(0, theme.muted())
            self.d_res.addTopLevelItem(it)
            if r is best:
                self.d_res.setCurrentItem(it)
        self._update_fav()
        self._update_buttons()

    def _selected_resource(self):
        it = self.d_res.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else None

    def _update_buttons(self):
        r = self._selected_resource()
        self.d_add.setEnabled(self.current is not None and (r is None or r.addable or r.kind == Kind.LINK))
        self.d_add.setText("Open link" if r is not None and r.kind == Kind.LINK else
                           "Set up & add…" if r is not None and r.kind in (Kind.STAC_COLLECTION,) else "Add to map")
        self.d_dl.setVisible(r is not None and r.kind in (Kind.WFS, Kind.ARCGIS_FEATURE, Kind.VECTOR_FILE))
        self.d_copy.setEnabled(r is not None and bool(r.url))

    def _add_selected(self, download=False):
        if self.current:
            self.actions.add(self.current, self._selected_resource(), download=download)

    def _copy_selected(self):
        r = self._selected_resource()
        if r:
            self.actions.copy_url(r)

    def _toggle_fav(self):
        if not self.current:
            return
        added = self.library.toggle_favorite(self.current)
        if added:
            self.model.favorites.add(self.current.key)
        else:
            self.model.favorites.discard(self.current.key)
        self.view.viewport().update()
        self._update_fav()
        self.actions.library_changed.emit()

    def _update_fav(self):
        fav = self.current is not None and self.library.is_favorite(self.current)
        self.d_fav.setIcon(theme.icon("star-filled", "#e0a400") if fav else theme.icon("star"))
        self.d_fav.setToolTip("Remove from favourites" if fav else "Add to favourites")

    def _context_menu(self, pos):
        idx = self.view.indexAt(pos)
        ds = idx.data(DATASET_ROLE) if idx.isValid() else None
        if ds is None:
            return
        m = QMenu(self)
        m.addAction(theme.icon("plus"), "Add best resource", lambda: self.actions.add(ds))
        if any(r.kind in (Kind.WFS, Kind.ARCGIS_FEATURE) for r in ds.resources):
            m.addAction(theme.icon("download"), "Download features in view",
                        lambda: self.actions.add(ds, ds.best_resource([Kind.WFS, Kind.ARCGIS_FEATURE]), download=True))
        wms = next((r for r in ds.resources if r.kind == Kind.WMS), None)
        if wms:
            m.addAction(theme.icon("map"), "Add as map image (WMS)", lambda: self.actions.add(ds, wms))
        m.addSeparator()
        fav = self.library.is_favorite(ds)
        m.addAction(theme.icon("star"), "Remove from favourites" if fav else "Add to favourites",
                    lambda: (self.view.setCurrentIndex(idx), self._toggle_fav()))
        if ds.page_url:
            m.addAction(theme.icon("external"), "Open dataset page", lambda: self.actions.open_page(ds))
        m.exec(self.view.viewport().mapToGlobal(pos))

    def _res_menu(self, pos):
        it = self.d_res.itemAt(pos)
        if not it:
            return
        r = it.data(0, Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        if r.addable:
            m.addAction(theme.icon("plus"), "Add to map", lambda: self.actions.add(self.current, r))
        if r.kind in (Kind.WFS, Kind.ARCGIS_FEATURE, Kind.VECTOR_FILE):
            m.addAction(theme.icon("download"), "Download features in view",
                        lambda: self.actions.add(self.current, r, download=True))
        if r.url:
            m.addAction(theme.icon("copy"), "Copy URL", lambda: self.actions.copy_url(r))
            m.addAction(theme.icon("external"), "Open URL in browser",
                        lambda: QDesktopServices.openUrl(QUrl(r.url)))
        m.exec(self.d_res.viewport().mapToGlobal(pos))


def _kind_icon(kind):
    return {
        Kind.WFS: "vector", Kind.ARCGIS_FEATURE: "vector", Kind.VECTOR_FILE: "vector",
        Kind.WMS: "map", Kind.WMTS: "map", Kind.XYZ: "map", Kind.ARCGIS_MAP: "map", Kind.ARCGIS_IMAGE: "map",
        Kind.COG: "layers", Kind.RASTER_FILE: "layers", Kind.STAC_COLLECTION: "satellite", Kind.DEM: "mountain",
        Kind.LINK: "link",
    }.get(kind, "info")
