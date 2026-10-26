# SPDX-License-Identifier: GPL-2.0-or-later
"""Paste any service or file URL; Datum works out what it is and adds it."""

import json

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel, QListWidget, QListWidgetItem, QFrame,
)

from ..core import net, tasks, settings
from ..core.models import Dataset, Kind, Resource
from ..core.sniff import guess_kind, resource_from_url, detect_capabilities, strip_query
from . import theme
from .widgets import hint, section

EXAMPLES = [
    ("WMS", "https://openmaps.gov.bc.ca/geo/pub/wms"),
    ("ArcGIS REST", "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
                    "World_Countries_(Generalized)/FeatureServer/0"),
    ("Cloud-optimised GeoTIFF", "https://canelevation-dem.s3.ca-central-1.amazonaws.com/"
                                "mrdem-30/mrdem-30-dtm-hillshade.tif"),
    ("XYZ tiles", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
    ("STAC API (save as a source)", "https://datacube.services.geo.ca/stac/api"),
    ("CKAN portal (save as a source)", "https://open.alberta.ca"),
]


class UrlTab(QWidget):
    def __init__(self, iface, actions, on_source_added, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.actions = actions
        self.on_source_added = on_source_added
        self.detected = None   # ("resource", Resource) | ("source", {name,url,type})

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        lay.addWidget(hint("Paste a WMS, WMTS, WFS, ArcGIS REST, XYZ, GeoTIFF/COG, GeoJSON, KML, zipped shapefile, "
                           "STAC API or CKAN portal URL. Query strings are fine."))
        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setObjectName("DatumSearch")
        self.url.setPlaceholderText("https://…")
        self.url.setClearButtonEnabled(True)
        self.url.addAction(theme.icon("url", theme.muted()), QLineEdit.ActionPosition.LeadingPosition)
        row.addWidget(self.url, 1)
        self.detect_btn = QPushButton("Detect")
        self.detect_btn.setObjectName("Ghost")
        row.addWidget(self.detect_btn)
        lay.addLayout(row)

        self.card = QFrame()
        self.card.setObjectName("Card")
        cl = QVBoxLayout(self.card)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(self.result)
        self.add_btn = QPushButton(theme.icon("plus", "#ffffff"), "Add to map")
        self.add_btn.setObjectName("Primary")
        cl.addWidget(self.add_btn)
        self.card.setVisible(False)
        lay.addWidget(self.card)

        lay.addWidget(section("Examples"))
        self.examples = QListWidget()
        self.examples.setObjectName("Library")
        for label, url in EXAMPLES:
            it = QListWidgetItem(theme.icon("link"), f"{label}\n{url}")
            it.setData(Qt.ItemDataRole.UserRole, url)
            it.setToolTip(url)
            self.examples.addItem(it)
        self.examples.setWordWrap(True)
        lay.addWidget(self.examples, 1)

        self.url.returnPressed.connect(self.detect)
        self.detect_btn.clicked.connect(self.detect)
        self.add_btn.clicked.connect(self.add)
        self.examples.itemClicked.connect(self._example_clicked)

    def _example_clicked(self, item):
        self.url.setText(item.data(Qt.ItemDataRole.UserRole))
        self.detect()

    def detect(self):
        url = self.url.text().strip()
        if not url:
            return
        if not url.lower().startswith(("http://", "https://", "s3://", "/vsi")):
            url = "https://" + url
            self.url.setText(url)
        kind = guess_kind(url)
        if kind != Kind.LINK:
            self._show_resource(resource_from_url(url))
            return
        self.result.setText("Inspecting…")
        self.card.setVisible(True)
        self.add_btn.setEnabled(False)
        tasks.run("Datum: inspecting URL", lambda task: self._probe(url), self._probed, silent=True)

    @staticmethod
    def _probe(url):
        """Fetch the URL (or well-known endpoints under it) and classify the response."""
        base = url.rstrip("/")
        # CKAN portal?
        try:
            st = net.fetch_json(f"{base}/api/3/action/status_show", timeout=10)
            if st.get("success") and isinstance(st.get("result"), dict):
                title = st["result"].get("site_title") or base
                return ("source", {"name": title, "url": base, "type": "ckan"})
        except net.NetworkError:
            pass
        body = net.fetch(url, timeout=20)
        head = body[:2000].lstrip()
        if head.startswith(b"<"):
            svc = detect_capabilities(body)
            if svc:
                return ("resource", Resource(url, svc, strip_query(url), svc.upper()))
            try:  # maybe the bare endpoint needs GetCapabilities
                for svc in ("WMS", "WFS", "WMTS"):
                    caps = net.fetch(strip_query(url), params={"service": svc, "request": "GetCapabilities"},
                                     timeout=15)
                    found = detect_capabilities(caps)
                    if found:
                        return ("resource", Resource(url, found, strip_query(url), found.upper()))
            except net.NetworkError:
                pass
            return ("unknown", "an HTML/XML page Datum doesn't recognise")
        if head[:1] in (b"{", b"["):
            data = json.loads(body.decode("utf-8", "replace"))
            if isinstance(data, dict):
                if "stac_version" in data and any(link.get("rel") == "search" for link in data.get("links", [])):
                    return ("source", {"name": data.get("title") or data.get("id") or url, "url": base, "type": "stac"})
                if data.get("type") in ("FeatureCollection", "Feature"):
                    return ("resource", Resource(url, Kind.VECTOR_FILE, url, "GeoJSON"))
            return ("unknown", "JSON that isn't GeoJSON, STAC or ArcGIS")
        if head[:4] in (b"II*\x00", b"MM\x00*"):
            return ("resource", Resource(url, Kind.COG, url, "GeoTIFF"))
        if head[:2] == b"PK":
            return ("resource", Resource(url, Kind.VECTOR_FILE, url, "ZIP"))
        return ("unknown", "a file type Datum doesn't recognise")

    def _probed(self, ok, result, error):
        if error or not result:
            self.result.setText(f"⚠ Couldn't reach that URL: {error}")
            return
        what, payload = result
        if what == "resource":
            self._show_resource(payload)
        elif what == "source":
            self.detected = ("source", payload)
            self.result.setText(f"<b>{payload['type'].upper()} catalogue</b>: {payload['name']}<br>"
                                f"<span>Save it as a source and it will be searched alongside the others.</span>")
            self.add_btn.setText("Save as a search source")
            self.add_btn.setEnabled(True)
        else:
            self.detected = None
            self.result.setText(f"⚠ This looks like {payload}.")

    def _show_resource(self, res):
        self.detected = ("resource", res)
        layer = f"<br>Layer: <code>{res.layer}</code>" if res.layer else ""
        more = "<br><span>You'll be able to pick layers next.</span>" if res.kind in (
            Kind.WMS, Kind.WFS, Kind.WMTS) and not res.layer or res.kind in (
            Kind.ARCGIS_MAP, Kind.ARCGIS_FEATURE) and res.layer == "" else ""
        self.result.setText(f"<b>{res.label}</b> detected{layer}{more}")
        self.add_btn.setText("Add to map")
        self.add_btn.setEnabled(True)
        self.card.setVisible(True)

    def add(self):
        if not self.detected:
            return
        what, payload = self.detected
        if what == "source":
            eps = settings.get("custom_endpoints")
            if not any(e["url"] == payload["url"] for e in eps):
                eps.append(payload)
                settings.set("custom_endpoints", eps)
            self.on_source_added(payload)
            self.result.setText(f"✓ Saved <b>{payload['name']}</b>. It's now in the Search tab's Sources menu.")
            self.add_btn.setEnabled(False)
            return
        res = payload
        url = self.url.text().strip()
        name = res.layer or url.rstrip("/").split("/")[-1].split("?")[0] or url
        ds = Dataset(id=url, title=name, source="url", source_label="Added by URL", page_url="", resources=[res])
        res.name = name
        self.actions.add(ds, res)
