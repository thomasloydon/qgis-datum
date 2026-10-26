# SPDX-License-Identifier: GPL-2.0-or-later
"""Turn Resources into QGIS layers and put them in the project."""

import os

from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer, QgsDataSourceUri, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsRectangle, QgsRasterBandStats, QgsSingleBandPseudoColorRenderer, QgsColorRampShader,
    QgsRasterShader, QgsHillshadeRenderer, QgsGradientColorRamp, QgsGradientStop, QgsRasterDataProvider,
    QgsAbstractMetadataBase,
)
from qgis.PyQt.QtGui import QColor, QPainter

from .models import Kind, Resource, Dataset
from .sniff import gdal_path
from . import settings

TERRAIN_STOPS = [
    (0.00, "#24693d"), (0.12, "#4f9a45"), (0.28, "#a5c46a"), (0.42, "#e9dc95"),
    (0.58, "#d0a35f"), (0.72, "#9c6b45"), (0.86, "#a89a90"), (1.00, "#fbfbfb"),
]


class LoadError(Exception):
    pass


# --------------------------------------------------------------------------- uri builders

def wms_uri(url, layer, crs="EPSG:3857", fmt="image/png", style=""):
    uri = QgsDataSourceUri()
    uri.setParam("url", url)
    uri.setParam("layers", layer)
    uri.setParam("styles", style)
    uri.setParam("format", fmt)
    uri.setParam("crs", crs)
    uri.setParam("dpiMode", "7")
    uri.setParam("contextualWMSLegend", "0")
    return bytes(uri.encodedUri()).decode()


def wmts_uri(url, layer, tile_matrix_set, fmt="image/png", style="default", crs="EPSG:3857"):
    uri = QgsDataSourceUri()
    uri.setParam("url", url)
    uri.setParam("layers", layer)
    uri.setParam("tileMatrixSet", tile_matrix_set)
    uri.setParam("format", fmt)
    uri.setParam("styles", style)
    uri.setParam("crs", crs)
    return bytes(uri.encodedUri()).decode()


def xyz_uri(url, zmin=0, zmax=19):
    uri = QgsDataSourceUri()
    uri.setParam("type", "xyz")
    uri.setParam("url", url)
    uri.setParam("zmin", str(zmin))
    uri.setParam("zmax", str(zmax))
    return bytes(uri.encodedUri()).decode()


def wfs_uri(url, typename, srs="", max_features=0, restrict_to_view=True):
    uri = QgsDataSourceUri()
    uri.setParam("url", url)
    uri.setParam("typename", typename)
    uri.setParam("version", "auto")
    uri.setParam("pagingEnabled", "true")
    uri.setParam("preferCoordinatesForWfsT11", "false")
    if srs:
        uri.setParam("srsname", srs)
    if restrict_to_view:
        uri.setParam("restrictToRequestBBOX", "1")
    if max_features:
        uri.setParam("maxNumFeatures", str(max_features))
    return uri.uri(False)


def arcgis_feature_uri(url, layer_id, crs=""):
    uri = QgsDataSourceUri()
    uri.setParam("url", f"{url.rstrip('/')}/{layer_id}" if layer_id != "" else url)
    if crs:
        uri.setParam("crs", crs)
    return uri.uri(False)


def arcgis_map_uri(url, layer_id="", crs="", fmt="PNG32"):
    uri = QgsDataSourceUri()
    uri.setParam("url", url)
    uri.setParam("format", fmt)
    if layer_id != "":
        uri.setParam("layer", str(layer_id))
    if crs:
        uri.setParam("crs", crs)
    return uri.uri(False)


# --------------------------------------------------------------------------- layer factory

def project_crs():
    crs = QgsProject.instance().crs()
    return crs.authid() if crs.isValid() else "EPSG:3857"


def make_layer(res: Resource, name=None, crs=None, wfs_restrict=True):
    """Create (but do not add) a QGIS layer for a resource."""
    name = name or res.name
    crs = crs or res.crs or project_crs()
    k = res.kind
    if k == Kind.WMS:
        if not res.layer:
            raise LoadError("Choose a layer from this WMS service first.")
        layer = QgsRasterLayer(wms_uri(res.url, res.layer, crs=res.extra.get("wms_crs") or crs,
                                       fmt=res.extra.get("format", "image/png"),
                                       style=res.extra.get("style", "")), name, "wms")
    elif k == Kind.WMTS:
        layer = QgsRasterLayer(wmts_uri(res.url, res.layer, res.extra.get("tile_matrix_set", "EPSG:3857"),
                                        fmt=res.extra.get("format", "image/png"),
                                        style=res.extra.get("style", "default"),
                                        crs=res.extra.get("crs", "EPSG:3857")), name, "wms")
    elif k == Kind.XYZ:
        layer = QgsRasterLayer(xyz_uri(res.url, zmax=res.extra.get("zmax", 19)), name, "wms")
    elif k == Kind.WFS:
        layer = QgsVectorLayer(wfs_uri(res.url, res.layer, srs=res.crs,
                                       max_features=settings.get("wfs_max_features"),
                                       restrict_to_view=wfs_restrict), name, "WFS")
        if res.extra.get("filter"):
            layer.setSubsetString(res.extra["filter"])
    elif k == Kind.ARCGIS_FEATURE:
        layer = QgsVectorLayer(arcgis_feature_uri(res.url, res.layer), name, "arcgisfeatureserver")
    elif k in (Kind.ARCGIS_MAP, Kind.ARCGIS_IMAGE):
        layer = QgsRasterLayer(arcgis_map_uri(res.url, res.layer), name, "arcgismapserver")
    elif k in (Kind.COG, Kind.RASTER_FILE):
        layer = QgsRasterLayer(gdal_path(res.url), name, "gdal")
    elif k == Kind.VECTOR_FILE:
        layer = QgsVectorLayer(gdal_path(res.url), name, "ogr")
    else:
        raise LoadError(f"{res.label} resources can't be added directly.")
    if not layer.isValid():
        err = layer.error().summary() if layer.error() else ""
        raise LoadError(f"QGIS could not open “{name}”. {err}".strip())
    return layer


# --------------------------------------------------------------------------- project helpers

def target_group(dataset: Dataset = None):
    root = QgsProject.instance().layerTreeRoot()
    name = settings.get("group_name")
    if not name:
        return root
    group = root.findGroup(name)
    if group is None:
        group = root.insertGroup(0, name)
    if settings.get("group_by_source") and dataset and dataset.source_label:
        sub = group.findGroup(dataset.source_label)
        if sub is None:
            sub = group.addGroup(dataset.source_label)
        group = sub
    return group


def apply_metadata(layer, dataset: Dataset = None, res: Resource = None):
    if not settings.get("add_metadata") or dataset is None:
        return
    md = layer.metadata()
    md.setTitle(dataset.title)
    md.setAbstract(dataset.description)
    if dataset.license:
        md.setLicenses([dataset.license])
    if dataset.organization:
        md.setRights([dataset.organization])
    md.setKeywords({"datum": dataset.tags[:20]} if dataset.tags else {})
    if dataset.page_url:
        link = QgsAbstractMetadataBase.Link("Source page", "WWW:LINK", dataset.page_url)
        md.addLink(link)
    layer.setMetadata(md)
    attribution = (res.extra.get("attribution") if res else "") or dataset.organization
    if attribution:
        try:
            layer.serverProperties().setAttribution(attribution)
        except AttributeError:  # QGIS < 3.28
            layer.setAttribution(attribution)


def add_to_project(layer, dataset: Dataset = None, res: Resource = None, zoom=None, group=None):
    apply_metadata(layer, dataset, res)
    project = QgsProject.instance()
    project.addMapLayer(layer, False)
    group = group or target_group(dataset)
    # basemaps go to the bottom, everything else on top
    if res is not None and res.kind == Kind.XYZ:
        group.addLayer(layer)
    else:
        group.insertLayer(0, layer)
    if zoom if zoom is not None else settings.get("zoom_to_layer"):
        zoom_to(layer)
    return layer


def zoom_to(layer):
    from qgis.utils import iface
    if iface is None:
        return
    canvas = iface.mapCanvas()
    extent = layer.extent()
    if extent.isEmpty():
        return
    ct = QgsCoordinateTransform(layer.crs(), canvas.mapSettings().destinationCrs(), QgsProject.instance())
    try:
        canvas.setExtent(ct.transformBoundingBox(extent))
        canvas.refresh()
    except Exception:  # noqa: BLE001 - transform failures shouldn't break adding
        pass


# --------------------------------------------------------------------------- raster styling

def terrain_ramp():
    first, last = TERRAIN_STOPS[0][1], TERRAIN_STOPS[-1][1]
    stops = [QgsGradientStop(p, QColor(c)) for p, c in TERRAIN_STOPS[1:-1]]
    return QgsGradientColorRamp(QColor(first), QColor(last), False, stops)


def band_range(layer, sample=40000):
    prov = layer.dataProvider()
    stats = prov.bandStatistics(1, QgsRasterBandStats.Stats.Min | QgsRasterBandStats.Stats.Max,
                                layer.extent(), sample)
    return stats.minimumValue, stats.maximumValue


def smooth_resampling(layer):
    """Bilinear (in) / average (out) resampling: nearest-neighbour on overviews streaks hillshades."""
    prov = layer.dataProvider()
    try:
        prov.enableProviderResampling(True)
        prov.setZoomedInResamplingMethod(QgsRasterDataProvider.ResamplingMethod.Bilinear)
        prov.setZoomedOutResamplingMethod(QgsRasterDataProvider.ResamplingMethod.Bilinear)
    except AttributeError:  # provider without resampling support
        pass


def style_elevation(layer, vmin=None, vmax=None):
    if vmin is None or vmax is None:
        vmin, vmax = band_range(layer)
    if vmax <= vmin:
        vmax = vmin + 1
    ramp = terrain_ramp()
    fn = QgsColorRampShader(vmin, vmax, ramp)
    fn.setColorRampType(QgsColorRampShader.Type.Interpolated)
    fn.classifyColorRamp(len(TERRAIN_STOPS) * 2, -1, layer.extent(), None)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fn)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    renderer.setClassificationMin(vmin)
    renderer.setClassificationMax(vmax)
    layer.setRenderer(renderer)
    smooth_resampling(layer)
    layer.triggerRepaint()


def style_hillshade(layer, multi=True, z=1.0):
    smooth_resampling(layer)
    r = QgsHillshadeRenderer(layer.dataProvider(), 1, 315, 45)
    r.setMultiDirectional(multi)
    r.setZFactor(z)
    layer.setRenderer(r)
    layer.triggerRepaint()


def style_dem(layer, style=None):
    style = style or settings.get("dem_style")
    try:
        if style == "elevation":
            style_elevation(layer)
        elif style == "hillshade":
            style_hillshade(layer)
    except Exception:  # noqa: BLE001 - styling must never block adding data
        pass


def add_blend_hillshade(source_layer, dataset=None, name=None, group=None):
    """Second copy of a DEM rendered as a multiplied hillshade on top of the colour ramp."""
    hs = QgsRasterLayer(source_layer.source(), name or f"{source_layer.name()} (hillshade)", "gdal")
    if not hs.isValid():
        return None
    style_hillshade(hs)
    hs.setBlendMode(QPainter.CompositionMode.CompositionMode_Multiply)
    hs.renderer().setOpacity(0.55)
    return add_to_project(hs, dataset, zoom=False, group=group)


# --------------------------------------------------------------------------- downloads (run in tasks)

def download_vector(res: Resource, bbox_ll, out_path, fmt="GPKG", feedback=None, max_features=0):
    """Save the features of a vector resource inside ``bbox_ll`` to a local file. Blocking."""
    from osgeo import gdal
    gdal.UseExceptions()
    layer_name = (res.layer.split(":")[-1].split(".")[-1] or "features").lower()
    if os.path.exists(out_path):
        gdal.GetDriverByName(fmt).Delete(out_path)

    def cb(complete, msg, data):
        if feedback:
            feedback.setProgress(complete * 100)
            return 0 if feedback.isCanceled() else 1
        return 1

    if res.kind == Kind.WFS:
        gdal.SetThreadLocalConfigOption("OGR_WFS_PAGING_ALLOWED", "ON")
        gdal.SetThreadLocalConfigOption("OGR_WFS_PAGE_SIZE", "5000")
        gdal.SetThreadLocalConfigOption("OGR_WFS_LOAD_MULTIPLE_LAYER_DEFN", "NO")
        # TYPENAME in the URL keeps GDAL from parsing every layer in large capabilities docs
        sep = "&" if "?" in res.url else "?"
        src = gdal.OpenEx(f"WFS:{res.url}{sep}TYPENAME={res.layer}", gdal.OF_VECTOR,
                          open_options=["EXPOSE_GML_ID=NO"])
        layers = [res.layer]
    elif res.kind == Kind.ARCGIS_FEATURE:
        src_url = f"{res.url.rstrip('/')}/{res.layer}/query?where=1%3D1&outFields=*&f=geojson"
        src = gdal.OpenEx(src_url, gdal.OF_VECTOR)
        layers = None
    else:
        src = gdal.OpenEx(gdal_path(res.url), gdal.OF_VECTOR)
        layers = None
    if src is None:
        raise LoadError("Could not open the remote data.")
    kw = dict(format=fmt, spatFilter=list(bbox_ll), spatSRS="EPSG:4326", callback=cb,
              layerName=layer_name if fmt != "ESRI Shapefile" else None, geometryType="PROMOTE_TO_MULTI")
    if layers:
        kw["layers"] = layers
    if max_features:
        kw["limit"] = int(max_features)
    out = gdal.VectorTranslate(out_path, src, **kw)
    if out is None:
        raise LoadError("Download failed.")
    count = sum(out.GetLayer(i).GetFeatureCount() for i in range(out.GetLayerCount()))
    out = None
    return out_path, count


def canvas_bbox_ll():
    """Current map extent as a lon/lat bbox (or None outside the QGIS GUI)."""
    from qgis.utils import iface
    if iface is None:
        return None
    canvas = iface.mapCanvas()
    return to_ll(canvas.extent(), canvas.mapSettings().destinationCrs())


def to_ll(rect: QgsRectangle, crs: QgsCoordinateReferenceSystem):
    wgs = QgsCoordinateReferenceSystem("EPSG:4326")
    if crs != wgs:
        ct = QgsCoordinateTransform(crs, wgs, QgsProject.instance())
        rect = ct.transformBoundingBox(rect)
    xmin, ymin = max(rect.xMinimum(), -180.0), max(rect.yMinimum(), -90.0)
    xmax, ymax = min(rect.xMaximum(), 180.0), min(rect.yMaximum(), 90.0)
    return (xmin, ymin, xmax, ymax)


def from_ll(bbox_ll, crs: QgsCoordinateReferenceSystem):
    rect = QgsRectangle(*bbox_ll)
    wgs = QgsCoordinateReferenceSystem("EPSG:4326")
    if crs != wgs:
        rect = QgsCoordinateTransform(wgs, crs, QgsProject.instance()).transformBoundingBox(rect)
    return rect
