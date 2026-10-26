# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline smoke test inside headless QGIS: no network, safe for every CI run.

Covers plugin load/unload, building the dock and every tab, URI builders,
and DEM styling + terrain products on a synthetic raster.

    python3 tests/qgis_smoke.py        (with QGIS's Python, QT_QPA_PLATFORM=offscreen)
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Sandbox settings/profile before QGIS starts (see qgis_integration.py)
SANDBOX = tempfile.mkdtemp(prefix="datum-smoke-")
os.environ["HOME"] = SANDBOX
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = SANDBOX
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.PyQt.QtCore import QSettings
from qgis.core import (
    QgsApplication, QgsProject, QgsCoordinateReferenceSystem, QgsRectangle, QgsRasterLayer, QgsVectorLayer,
    QgsSingleBandPseudoColorRenderer, QgsHillshadeRenderer, QgsDataSourceUri,
)

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, SANDBOX)
app = QgsApplication([], True)
app.initQgis()

from qgis.testing.mocked import get_iface
import qgis.utils

iface = get_iface()
qgis.utils.iface = iface
canvas = iface.mapCanvas()
canvas.resize(800, 600)
crs = QgsCoordinateReferenceSystem("EPSG:3005")
QgsProject.instance().setCrs(crs)
canvas.setDestinationCrs(crs)
canvas.setExtent(QgsRectangle(1210000, 480000, 1214000, 483000))

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        failures.append(name)


def synthetic_dem(path, size=200, res=10.0):
    """A smooth cone-shaped hill in BC Albers, written with GDAL."""
    from osgeo import gdal, osr
    import math
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, size, size, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((1210000, res, 0, 483000, 0, -res))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3005)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767)
    import array
    c = size / 2
    vals = array.array("f", [max(0.0, 500 - 4 * math.hypot(x - c, y - c)) for y in range(size) for x in range(size)])
    band.WriteRaster(0, 0, size, size, vals.tobytes())
    ds = None
    return path


try:
    # ---------------------------------------------------------------- plugin lifecycle
    import datum
    plugin = datum.classFactory(iface)
    plugin.initGui()
    plugin.toggle(True)
    check("plugin opens dock", plugin.dock is not None and plugin.dock.tabs.count() == 6)
    dock = plugin.dock

    # ---------------------------------------------------------------- tabs
    st = dock.search_tab
    check("sources menu", len(st.sources_menu.actions()) == len(dock.registry) >= 6)
    q = dock.quick_tab
    n_items = sum(q.tree.topLevelItem(i).childCount() for i in range(q.tree.topLevelItemCount()))
    check("quick picks populated", n_items > 30, f"{n_items} items")
    q.filter.setText("streams")
    visible = [it for _, it in q._iter_children() if not it.isHidden()]
    check("quick filter", len(visible) >= 1 and all("stream" in it.text(0).lower() for it in visible))
    req = dock.dem_tab.build_request()
    check("dem request", req.bbox_ll is not None and req.target_bounds[0] < req.target_bounds[2])

    # ---------------------------------------------------------------- uri builders
    from datum.core import loader
    from datum.core.models import Resource, Kind
    wms = loader.wms_uri("https://x/wms?map=a&b=c", "pub:L", crs="EPSG:3005")
    # QGIS versions differ in how much they percent-encode, so check the round trip instead
    parsed = QgsDataSourceUri()
    parsed.setEncodedUri(wms)
    check("wms uri keeps query url intact",
          (parsed.param("url"), parsed.param("layers"), parsed.param("crs")) == ("https://x/wms?map=a&b=c", "pub:L", "EPSG:3005"),
          wms)
    wfs = loader.wfs_uri("https://x/wfs", "pub:L", srs="EPSG:3005")
    check("wfs uri", "typename='pub:L'" in wfs and "restrictToRequestBBOX='1'" in wfs, wfs)
    check("xyz uri", "type=xyz" in loader.xyz_uri("https://t/{z}/{x}/{y}.png"))

    # ---------------------------------------------------------------- DEM styling & products
    from datum.core.dem import DemBuilder, DemRequest
    tif = synthetic_dem(os.path.join(SANDBOX, "hill.tif"))
    layer = QgsRasterLayer(tif, "hill")
    check("synthetic dem valid", layer.isValid())
    loader.style_elevation(layer)
    check("elevation renderer", isinstance(layer.renderer(), QgsSingleBandPseudoColorRenderer))
    hs = loader.add_blend_hillshade(layer)
    check("blend hillshade", hs is not None and isinstance(hs.renderer(), QgsHillshadeRenderer))

    out = os.path.join(SANDBOX, "out")
    os.makedirs(out)
    b = DemBuilder({})
    r = DemRequest(source_id="x", surface="dtm", bbox_ll=(0, 0, 1, 1), target_crs_wkt="", target_bounds=(0, 0, 1, 1),
                   hillshade=True, slope=True, aspect=True, roughness=True, tri=True, tpi=True,
                   contours=True, contour_interval=50, out_dir=out)

    class Result:
        dem_path = tif
        outputs = {}

    res = Result()
    b._derivatives(r, res, ["TILED=YES", "COMPRESS=DEFLATE", "PREDICTOR=3"])
    check("terrain products", set(res.outputs) == {"hillshade", "slope", "aspect", "roughness", "tri", "tpi", "contours"},
          str(sorted(res.outputs)))
    check("products open", all(QgsRasterLayer(p).isValid() for k, p in res.outputs.items() if k != "contours"))
    check("contours generated", QgsVectorLayer(res.outputs["contours"]).featureCount() > 0)

    # ---------------------------------------------------------------- library
    from datum.core.models import Dataset
    ds = Dataset("x", "X", "bcdc", resources=[Resource("r", Kind.WFS, "u", layer="l")])
    lib = dock.library
    lib.toggle_favorite(ds)
    dock.library_tab.refresh()
    check("favourites", lib.is_favorite(ds) and dock.library_tab.favs.count() == 1)

    plugin.unload()
    check("plugin unloads", plugin.dock is None)
except Exception:  # noqa: BLE001 - report as a failure, keep the summary
    import traceback
    traceback.print_exc()
    failures.append("exception")

QgsProject.instance().clear()
print("\nFAILED: " + ", ".join(failures) if failures else "\nAll smoke checks passed.")
# skip interpreter teardown: tearing down QGIS with a mocked iface can segfault after the results are in
sys.stdout.flush()
os._exit(1 if failures else 0)
