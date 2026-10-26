# SPDX-License-Identifier: GPL-2.0-or-later
"""The Datum dock: header, tabs and status footer."""

from qgis.PyQt.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QProgressBar

from ..core import settings, net
from ..core.providers import build_registry
from ..core.store import Library
from . import theme
from .actions import DataActions
from .search_tab import SearchTab
from .quick_tab import QuickTab
from .dem_tab import DemTab
from .url_tab import UrlTab
from .library_tab import LibraryTab
from .settings_tab import SettingsTab


class DatumDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("Datum", parent)
        self.iface = iface
        self.setObjectName("DatumDock")
        self.setMinimumWidth(360)
        net.set_timeout(settings.get("timeout"))
        self.registry = self._build_registry()
        self.library = Library(settings.data_dir())
        self.actions = DataActions(iface, self.registry, self.library, self)

        root = QWidget()
        root.setObjectName("DatumRoot")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QWidget()
        header.setObjectName("DatumHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 8, 10, 8)
        logo = QLabel()
        logo.setPixmap(theme.accent_icon("logo", 30).pixmap(30, 30))
        hl.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel("Datum")
        t.setObjectName("DatumTitle")
        s = QLabel("Open data, found and added")
        s.setObjectName("DatumSubtitle")
        titles.addWidget(t)
        titles.addWidget(s)
        hl.addLayout(titles, 1)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setFixedWidth(48)
        self.busy.setVisible(False)
        hl.addWidget(self.busy)
        lay.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("DatumTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.search_tab = SearchTab(iface, self.actions, lambda: self.registry, self.library)
        self.quick_tab = QuickTab(iface, self.actions)
        self.dem_tab = DemTab(iface, self.actions)
        self.settings_tab = SettingsTab(iface)
        self.url_tab = UrlTab(iface, self.actions, self.settings_tab.add_endpoint)
        self.library_tab = LibraryTab(iface, self.actions, self.library)
        for w, ic, label, tip in [
            (self.search_tab, "search", "Search", "Search every catalogue at once"),
            (self.quick_tab, "zap", "Quick add", "Verified layers in one click"),
            (self.dem_tab, "mountain", "Elevation", "Build a DEM, hillshade, slope, contours…"),
            (self.url_tab, "url", "URL", "Add any service or file by URL"),
            (self.library_tab, "star", "Library", "Favourites and recent layers"),
            (self.settings_tab, "settings", "", "Settings"),
        ]:
            i = self.tabs.addTab(w, theme.icon(ic), label)
            self.tabs.setTabToolTip(i, tip)
        lay.addWidget(self.tabs, 1)

        self.footer = QLabel("")
        self.footer.setObjectName("Hint")
        self.footer.setContentsMargins(10, 3, 10, 4)
        lay.addWidget(self.footer)
        self.setWidget(root)
        self.apply_style()

        self.tabs.setCurrentIndex(min(settings.get("last_tab"), self.tabs.count() - 1))
        self.tabs.currentChanged.connect(lambda i: settings.set("last_tab", i))
        self.actions.busy.connect(self.busy.setVisible)
        self.actions.status.connect(self.footer.setText)
        self.actions.library_changed.connect(self.library_tab.refresh)
        self.settings_tab.changed.connect(self._rebuild)

    @staticmethod
    def _build_registry():
        return build_registry(settings.get("custom_endpoints"), lang=settings.get("lang"))

    def _rebuild(self):
        self.registry = self._build_registry()
        self.actions.registry = self.registry
        self.search_tab.rebuild_sources_menu()

    def apply_style(self):
        self.widget().setStyleSheet(theme.stylesheet())

    def focus_search(self):
        self.tabs.setCurrentWidget(self.search_tab)
        self.search_tab.box.setFocus()
        self.search_tab.box.selectAll()
