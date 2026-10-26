# SPDX-License-Identifier: GPL-2.0-or-later
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon

try:
    from qgis.PyQt.QtWidgets import QAction
except ImportError:  # Qt6
    from qgis.PyQt.QtGui import QAction

ICON = os.path.join(os.path.dirname(__file__), "icons", "datum.svg")


class DatumPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None
        self.search_action = None

    def initGui(self):
        self.action = QAction(QIcon(ICON), "Datum — find open data", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("Search and add open data: BC Data Catalogue, Open Canada, NRCan DEMs, STAC…")
        self.action.toggled.connect(self.toggle)
        self.search_action = QAction(QIcon(ICON), "Datum: search open data…", self.iface.mainWindow())
        self.search_action.triggered.connect(self.focus_search)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToWebMenu("&Datum", self.action)
        self.iface.addPluginToWebMenu("&Datum", self.search_action)
        self.iface.registerMainWindowAction(self.search_action, "Ctrl+Alt+D")

    def unload(self):
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        for a in (self.action, self.search_action):
            if a:
                self.iface.removePluginWebMenu("&Datum", a)
        if self.search_action:
            self.iface.unregisterMainWindowAction(self.search_action)
        if self.action:
            self.iface.removeToolBarIcon(self.action)

    def _ensure_dock(self):
        if self.dock is None:
            from .ui.dock import DatumDock
            self.dock = DatumDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self.dock.visibilityChanged.connect(self._sync_action)
        return self.dock

    def _sync_action(self, _visible):
        # isHidden() stays False when the dock is merely tabbed behind another one
        self.action.blockSignals(True)
        self.action.setChecked(not self.dock.isHidden())
        self.action.blockSignals(False)

    def toggle(self, on):
        dock = self._ensure_dock()
        dock.setVisible(on)
        if on:
            dock.raise_()

    def focus_search(self):
        dock = self._ensure_dock()
        dock.show()
        dock.raise_()
        self.action.blockSignals(True)
        self.action.setChecked(True)
        self.action.blockSignals(False)
        dock.focus_search()
