# SPDX-License-Identifier: GPL-2.0-or-later
"""One place that knows how to bring any Dataset/Resource into the map.

Every tab calls ``DataActions.add``; this routes to live services, downloads,
STAC item search, the DEM builder, or a layer picker as needed.
"""

import os
from urllib.parse import urlsplit

from qgis.PyQt.QtCore import QObject, pyqtSignal, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QPainter
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import (
    Qgis, QgsProject, QgsRasterLayer, QgsVectorLayer, QgsCoordinateReferenceSystem,
)

from ..core import net, settings, tasks, loader
from ..core.models import Kind, Resource, Dataset
from ..core.sniff import (
    parse_wms_capabilities, parse_wmts_capabilities, parse_wfs_capabilities, pick_crs,
)
from ..core.dem import DemBuilder, DemRequest, SOURCES_BY_ID, AUTO, safe_name, bbox_area_km2

QUICK_STREAM_KM2 = 25000   # one-click DEMs larger than this stream instead of downloading
from .dialogs import LayerPickerDialog, StacDialog


class DataActions(QObject):
    status = pyqtSignal(str)            # short status text for the dock footer
    busy = pyqtSignal(bool)
    library_changed = pyqtSignal()

    def __init__(self, iface, registry, library, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.registry = registry
        self.library = library
        self._busy = 0
        self._dialogs = []

    # ------------------------------------------------------------------ feedback
    def _push(self, text, level=Qgis.MessageLevel.Info, duration=5):
        if self.iface:
            self.iface.messageBar().pushMessage("Datum", text, level, duration)
        self.status.emit(text)

    def _start(self, text):
        self._busy += 1
        self.busy.emit(True)
        self.status.emit(text)

    def _stop(self):
        self._busy = max(0, self._busy - 1)
        if not self._busy:
            self.busy.emit(False)

    def _parent(self):
        return self.iface.mainWindow() if self.iface else None

    def _record(self, ds, res, layer):
        if ds is not None:
            self.library.record(ds, res, layer.name())
            self.library_changed.emit()

    # ------------------------------------------------------------------ routing
    def preferred_kinds(self, ds: Dataset):
        mode = settings.get("bc_default")
        if mode == "wms":
            return [Kind.WMS]
        return [Kind.DEM, Kind.WFS]

    def add(self, ds: Dataset, res: Resource = None, download=False):
        res = res or ds.best_resource(self.preferred_kinds(ds))
        if res is None:
            if ds.page_url:
                self._push("Nothing here can be added directly; opening the dataset page.")
                self.open_page(ds)
            return
        try:
            if res.kind == Kind.DEM:
                return self.quick_dem(ds, res)
            if res.kind == Kind.STAC_COLLECTION:
                return self.open_stac(ds, res)
            if res.kind == Kind.LINK:
                return QDesktopServices.openUrl(QUrl(res.url))
            if res.kind in (Kind.WFS, Kind.ARCGIS_FEATURE, Kind.VECTOR_FILE) and (
                    download or (res.kind == Kind.WFS and settings.get("bc_default") == "download")):
                return self.download_vector(ds, res)
            if res.kind == Kind.WMS and not res.layer:
                return self.pick_service_layers(ds, res, "wms")
            if res.kind == Kind.WMTS and not res.extra.get("tile_matrix_set"):
                return self.pick_service_layers(ds, res, "wmts")
            if res.kind == Kind.WFS and not res.layer:
                return self.pick_service_layers(ds, res, "wfs")
            if res.kind in (Kind.ARCGIS_FEATURE, Kind.ARCGIS_MAP) and res.layer == "":
                return self.pick_arcgis_layers(ds, res)
            self.add_now(ds, res)
        except loader.LoadError as e:
            self._push(str(e), Qgis.MessageLevel.Warning)

    def add_now(self, ds, res, name=None):
        if res.kind == Kind.WMS and not res.extra.get("wms_crs") and urlsplit(res.url).hostname == "openmaps.gov.bc.ca":
            res.extra["wms_crs"] = "EPSG:3857"
        layer = loader.make_layer(res, name or self._layer_name(ds, res))
        style = res.extra.get("style")
        if style == "elevation":
            loader.style_dem(layer, "elevation")
        elif style == "hillshade":
            loader.style_hillshade(layer)
        loader.add_to_project(layer, ds, res)
        self._record(ds, res, layer)
        self._push(f"Added “{layer.name()}”.", Qgis.MessageLevel.Success, 3)
        return layer

    @staticmethod
    def _layer_name(ds, res):
        if ds is None:
            return res.name
        if res.kind == Kind.WMS and res.extra.get("object_name"):
            return f"{ds.title} (WMS)"
        if res.kind in (Kind.WFS, Kind.ARCGIS_FEATURE, Kind.COG, Kind.XYZ):
            return ds.title
        return res.name if res.name and res.name != res.url else ds.title

    def open_page(self, ds):
        if ds.page_url:
            QDesktopServices.openUrl(QUrl(ds.page_url))

    def copy_url(self, res: Resource):
        QApplication.clipboard().setText(res.url)
        self._push("URL copied to clipboard.", duration=2)

    # ------------------------------------------------------------------ services
    def pick_service_layers(self, ds, res, service):
        self._start(f"Reading {service.upper()} capabilities…")
        url = res.url

        def work(task):
            body = net.fetch(url, params={"service": service.upper(), "request": "GetCapabilities"})
            parser = {"wms": parse_wms_capabilities, "wmts": parse_wmts_capabilities,
                      "wfs": parse_wfs_capabilities}[service]
            return parser(body)

        def done(ok, layers, error):
            self._stop()
            if error or not layers:
                self._push(f"Couldn't read the service: {error or 'no layers found'}", Qgis.MessageLevel.Warning)
                return
            if len(layers) == 1:
                chosen = layers
            else:
                dlg = LayerPickerDialog(f"{ds.title if ds else url}", layers, self._parent())
                if not dlg.exec():
                    return
                chosen = dlg.selected()
            for l in chosen:
                r = Resource(name=l["title"], kind=res.kind, url=url, format=res.format, layer=l["name"],
                             extra=dict(res.extra))
                if service == "wms":
                    r.extra["wms_crs"] = pick_crs(l.get("crs"), loader.project_crs())
                elif service == "wmts":
                    tms = l.get("tile_matrix_sets") or ["EPSG:3857"]
                    pref = next((t for t in tms if "3857" in t or "GoogleMaps" in t), tms[0])
                    r.extra.update(tile_matrix_set=pref, format=(l.get("formats") or ["image/png"])[0],
                                   style=(l.get("styles") or ["default"])[0])
                elif service == "wfs" and l.get("crs"):
                    r.crs = l["crs"][0].replace("urn:ogc:def:crs:EPSG::", "EPSG:")
                try:
                    self.add_now(ds, r, name=l["title"])
                except loader.LoadError as e:
                    self._push(str(e), Qgis.MessageLevel.Warning)

        tasks.run(f"Datum: reading {service.upper()} capabilities", work, done, silent=True)

    def pick_arcgis_layers(self, ds, res):
        self._start("Reading ArcGIS service…")

        def work(task):
            return net.fetch_json(res.url, params={"f": "json"})

        def done(ok, info, error):
            self._stop()
            if error or not info:
                self._push(f"Couldn't read the ArcGIS service: {error}", Qgis.MessageLevel.Warning)
                return
            layers = [{"name": str(l["id"]), "title": l.get("name", str(l["id"])), "abstract": l.get("type", "")}
                      for l in info.get("layers", []) + info.get("tables", []) if "id" in l]
            if not layers:
                self._push("No layers found in this service.", Qgis.MessageLevel.Warning)
                return
            dlg = LayerPickerDialog(ds.title if ds else res.url, layers, self._parent())
            if not dlg.exec():
                return
            for l in dlg.selected():
                r = Resource(l["title"], res.kind, res.url, res.format, l["name"], extra=dict(res.extra))
                try:
                    self.add_now(ds, r, name=l["title"])
                except loader.LoadError as e:
                    self._push(str(e), Qgis.MessageLevel.Warning)

        tasks.run("Datum: reading ArcGIS service", work, done, silent=True)

    # ------------------------------------------------------------------ downloads
    def download_vector(self, ds, res, bbox_ll=None):
        bbox_ll = bbox_ll or loader.canvas_bbox_ll()
        if not bbox_ll:
            self._push("No map extent available to clip to.", Qgis.MessageLevel.Warning)
            return
        fmt = settings.get("wfs_download_format")
        ext = {"GPKG": ".gpkg", "GeoJSON": ".geojson", "ESRI Shapefile": ".shp"}[fmt]
        out = os.path.join(settings.download_dir(create=True), safe_name(ds.title if ds else res.name) + ext)
        n = 2
        root = out[:-len(ext)]
        while os.path.exists(out):
            out = f"{root}_{n}{ext}"
            n += 1
        title = ds.title if ds else res.name
        self._start(f"Downloading {title}…")
        max_features = settings.get("wfs_max_features")

        def work(task):
            return loader.download_vector(res, bbox_ll, out, fmt, feedback=task, max_features=max_features)

        def done(ok, result, error):
            self._stop()
            if error or not ok:
                self._push(f"Download failed: {error}" if error else "Download canceled.",
                           Qgis.MessageLevel.Warning)
                return
            path, count = result
            layer = QgsVectorLayer(path, title, "ogr")
            if not layer.isValid():
                self._push(f"Downloaded to {path} but QGIS couldn't open it.", Qgis.MessageLevel.Warning)
                return
            loader.add_to_project(layer, ds, res)
            self._record(ds, res, layer)
            self._push(f"Saved {count:,} features to {os.path.basename(path)}.", Qgis.MessageLevel.Success)

        tasks.run(f"Datum: downloading {title}", work, done)

    # ------------------------------------------------------------------ STAC
    def open_stac(self, ds, res):
        provider = self.registry.get(res.extra.get("provider") or ds.source)
        if provider is None or not hasattr(provider, "search_items"):
            self._push("That STAC source is disabled in settings.", Qgis.MessageLevel.Warning)
            return
        dlg = StacDialog(self.iface, provider, res.layer, ds.title, self._parent(), preset=res.extra.get("preset"),
                         on_add=lambda *a: self.add_stac_items(ds, *a))
        self._dialogs.append(dlg)
        dlg.finished.connect(lambda *_: (dlg.aoi.clear_band(), self._dialogs.remove(dlg) if dlg in self._dialogs else None))
        dlg.show()

    def add_stac_items(self, ds, provider, collection, items, key, mosaic, download, bbox_ll):
        hrefs = [(it.get("id"), provider.asset_href(it, key)) for it in items]
        hrefs = [(i, h) for i, h in hrefs if h]
        if not hrefs:
            self._push("Those items don't have that asset.", Qgis.MessageLevel.Warning)
            return
        out_dir = os.path.join(settings.download_dir(), "stac")
        os.makedirs(out_dir, exist_ok=True)
        base = safe_name(f"{collection}_{key}_{hrefs[0][0]}")
        name = f"{ds.title} · {key}" if len(hrefs) == 1 or mosaic else None
        if not mosaic and not download:
            for item_id, h in hrefs:
                r = Resource(f"{item_id} · {key}", Kind.COG, h, "COG")
                try:
                    self.add_now(ds, r, name=f"{item_id} · {key}")
                except loader.LoadError as e:
                    self._push(str(e), Qgis.MessageLevel.Warning)
            return
        project_crs = QgsProject.instance().crs()
        target = project_crs if project_crs.isValid() else QgsCoordinateReferenceSystem("EPSG:3857")
        bounds = loader.from_ll(bbox_ll, target) if bbox_ll else None
        wkt = target.toWkt()
        self._start("Preparing imagery…")

        def work(task):
            from osgeo import gdal
            gdal.UseExceptions()
            gdal.SetThreadLocalConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
            outputs = []
            groups = [hrefs] if mosaic else [[h] for h in hrefs]
            for gi, group in enumerate(groups):
                if task.isCanceled():
                    break
                vsis = ["/vsicurl/" + h for _, h in group]
                stem = base if mosaic else safe_name(f"{collection}_{key}_{group[0][0]}")
                vrt = os.path.join(out_dir, stem + ".vrt")
                gdal.BuildVRT(vrt, vsis)
                if download and bounds is not None:
                    tif = os.path.join(out_dir, stem + ".tif")
                    gdal.Warp(tif, vrt, dstSRS=wkt, format="GTiff",
                              outputBounds=(bounds.xMinimum(), bounds.yMinimum(), bounds.xMaximum(), bounds.yMaximum()),
                              creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"], multithread=True,
                              callback=lambda c, m, d: (task.setProgress((gi + c) / len(groups) * 100),
                                                        0 if task.isCanceled() else 1)[1])
                    os.remove(vrt)
                    outputs.append((group[0][0], tif))
                else:
                    outputs.append((group[0][0], vrt))
            return outputs

        def done(ok, outputs, error):
            self._stop()
            if error or not ok:
                self._push(f"Couldn't prepare imagery: {error}" if error else "Canceled.", Qgis.MessageLevel.Warning)
                return
            for item_id, path in outputs:
                layer = QgsRasterLayer(path, name or f"{item_id} · {key}", "gdal")
                if not layer.isValid():
                    self._push(f"QGIS couldn't open {os.path.basename(path)}", Qgis.MessageLevel.Warning)
                    continue
                if any(t in collection for t in ("dem", "dtm", "dsm", "3dep", "elevation")) and layer.bandCount() == 1:
                    loader.style_dem(layer)
                r = Resource(layer.name(), Kind.COG, path, "GeoTIFF" if path.endswith(".tif") else "VRT")
                loader.add_to_project(layer, ds, r)
                self._record(ds, r, layer)
            self._push(f"Added {len(outputs)} layer{'s' if len(outputs) != 1 else ''}.", Qgis.MessageLevel.Success)

        tasks.run(f"Datum: preparing {collection} imagery", work, done)

    # ------------------------------------------------------------------ DEM
    def quick_dem(self, ds, res):
        """One-click DEM for the current map extent using saved defaults."""
        bbox = loader.canvas_bbox_ll()
        if not bbox:
            return
        canvas = self.iface.mapCanvas()
        crs = canvas.mapSettings().destinationCrs()
        rect = canvas.extent()
        # Over big areas a download is slow and coarse anyway; stream a VRT instead (instant,
        # QGIS reads the COG overviews it needs while you pan). The Elevation tab can still force a download.
        stream = bbox_area_km2(bbox) > QUICK_STREAM_KM2
        if stream:
            self._push(f"Large area (~{bbox_area_km2(bbox):,.0f} km²): streaming the DEM instead of downloading it. "
                       "Zoom in, or use the Elevation tab, for a local GeoTIFF.", duration=8)
        req = DemRequest(
            source_id=res.layer or AUTO, surface="dtm", bbox_ll=bbox, target_crs_wkt=crs.toWkt(),
            target_bounds=(rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()),
            target_is_geographic=crs.isGeographic(), mode="stream" if stream else "download",
            out_dir=os.path.join(settings.download_dir(), "dem"), max_mb=settings.get("dem_max_mb"),
            name=f"{res.layer or 'best'}_dtm",
        )
        self.run_dem(req, ds)

    def run_dem(self, req: DemRequest, ds=None, on_done=None, on_task=None):
        label = "best available DEM" if req.source_id == AUTO else SOURCES_BY_ID[req.source_id].title
        self._start(f"Building {label}…")

        def work(task):
            return DemBuilder(self.registry, feedback=task).run(req)

        def done(ok, result, error):
            self._stop()
            if on_done:
                on_done(ok, result, error)
            if error or not ok:
                self._push(f"Elevation failed: {error}" if error else "Elevation canceled.",
                           Qgis.MessageLevel.Warning, 8)
                return
            self.add_dem_result(result, req, ds)

        task = tasks.run(f"Datum: {label}", work, done)
        if on_task:
            on_task(task)
        return task

    def add_dem_result(self, result, req, ds=None):
        src = result.source
        title = f"{src.title.split(' (')[0]} {result.surface.upper()}"
        if not result.streamed:
            title += f" {result.resolution:g} m"
        meta = Dataset(id=src.id, title=title, source="dem", source_label="Datum elevation",
                       description=src.description, license=src.license, organization=src.title)
        group = loader.target_group(meta)
        layer = QgsRasterLayer(result.dem_path, title, "gdal")
        if not layer.isValid():
            self._push(f"Couldn't open {result.dem_path}", Qgis.MessageLevel.Warning)
            return
        style = settings.get("dem_style")
        loader.style_dem(layer, style)
        res = Resource(title, Kind.COG, result.dem_path, "GeoTIFF")
        added = [loader.add_to_project(layer, meta, res, zoom=False, group=group)]
        hs_path = result.outputs.get("hillshade")
        if style == "elevation" and settings.get("dem_blend_hillshade") and not hs_path:
            added.append(loader.add_blend_hillshade(layer, meta, group=group))
        for key, path in result.outputs.items():
            nice = {"hillshade": "hillshade", "slope": "slope", "aspect": "aspect", "roughness": "roughness",
                    "tri": "terrain ruggedness", "tpi": "topographic position", "contours": "contours"}[key]
            if key == "contours":
                lyr = QgsVectorLayer(path, f"{title} {nice} ({req.contour_interval:g} m)", "ogr")
            else:
                lyr = QgsRasterLayer(path, f"{title} {nice}", "gdal")
            if not lyr.isValid():
                continue
            if key == "hillshade" and style == "elevation":
                lyr.setBlendMode(QPainter.CompositionMode.CompositionMode_Multiply)
                lyr.renderer().setOpacity(0.55)
            elif key in ("slope", "roughness", "tri"):
                self._style_magma(lyr)
            added.append(loader.add_to_project(lyr, meta, Resource(lyr.name(), Kind.COG, path), zoom=False,
                                               group=group))
        if ds is not None:
            self._record(ds, res, layer)
        msg = f"Added {title} ({result.tiles} tile{'s' if result.tiles != 1 else ''})."
        if result.messages:
            msg += " " + " ".join(result.messages)
        self._push(msg, Qgis.MessageLevel.Success, 8)

    @staticmethod
    def _style_magma(layer):
        from qgis.core import QgsStyle, QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer
        try:
            ramp = QgsStyle.defaultStyle().colorRamp("Magma") or QgsStyle.defaultStyle().colorRamp("Viridis")
            vmin, vmax = loader.band_range(layer)
            fn = QgsColorRampShader(vmin, vmax, ramp)
            fn.setColorRampType(QgsColorRampShader.Type.Interpolated)
            fn.classifyColorRamp(10, -1, layer.extent(), None)
            sh = QgsRasterShader()
            sh.setRasterShaderFunction(fn)
            layer.setRenderer(QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, sh))
        except Exception:  # noqa: BLE001
            pass
