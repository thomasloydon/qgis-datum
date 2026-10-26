# SPDX-License-Identifier: GPL-2.0-or-later
"""Work out what a URL points at, and parse the service descriptions we care about.

Pure Python: used by the CKAN provider to classify resources and by the
"Add by URL" tab to auto-detect services.
"""

import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, parse_qsl, urlunsplit

from .models import Kind, Resource

VECTOR_EXT = {".geojson", ".json", ".kml", ".kmz", ".gpkg", ".shp", ".gml", ".fgb", ".csv", ".parquet"}
RASTER_EXT = {".tif", ".tiff", ".vrt", ".img", ".jp2", ".asc", ".nc", ".dem"}

# CKAN "format" strings (lower-cased) -> kind
FORMAT_KINDS = {
    "wms": Kind.WMS, "wmts": Kind.WMTS, "wfs": Kind.WFS,
    "esri rest": None, "arcgis rest": None, "arcgis_rest": None, "esri_rest": None,  # resolved from the URL
    "geojson": Kind.VECTOR_FILE, "kml": Kind.VECTOR_FILE, "kmz": Kind.VECTOR_FILE,
    "gpkg": Kind.VECTOR_FILE, "geopackage": Kind.VECTOR_FILE, "shp": Kind.VECTOR_FILE,
    "shapefile": Kind.VECTOR_FILE, "gml": Kind.VECTOR_FILE, "fgb": Kind.VECTOR_FILE,
    "geotiff": Kind.COG, "tiff": Kind.COG, "tif": Kind.COG, "cog": Kind.COG,
    "xyz": Kind.XYZ,
}

LINK_FORMATS = {"html", "pdf", "doc", "docx", "xls", "xlsx", "txt", "openapi", "api", "ftp"}


def strip_query(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def query_dict(url):
    return {k.lower(): v for k, v in parse_qsl(urlsplit(url).query, keep_blank_values=True)}


def ext_of(url):
    path = urlsplit(url).path.lower()
    m = re.search(r"(\.[a-z0-9]+)$", path)
    return m.group(1) if m else ""


def s3_to_https(href):
    """s3://bucket/key -> https://bucket.s3.amazonaws.com/key (public buckets)."""
    if href.startswith("s3://"):
        bucket, _, key = href[5:].partition("/")
        return f"https://{bucket}.s3.amazonaws.com/{key}"
    return href


def arcgis_kind(url):
    """Classify an ArcGIS REST URL. Returns (kind, base_url, layer_id) or None."""
    m = re.search(r"^(.*?/rest/services/.+?/(FeatureServer|MapServer|ImageServer))(?:/(\d+))?", url, re.I)
    if not m:
        return None
    base, svc, layer = m.group(1), m.group(2).lower(), m.group(3)
    if svc == "featureserver" or (svc == "mapserver" and layer is not None and "/query" in url.lower()):
        return Kind.ARCGIS_FEATURE, base, layer
    if svc == "imageserver":
        return Kind.ARCGIS_IMAGE, base, layer
    return Kind.ARCGIS_MAP, base, layer


def guess_kind(url, fmt=""):
    """Best guess of a resource kind from its URL and an optional declared format."""
    fmt = (fmt or "").strip().lower()
    low = url.lower()
    if not url:
        return Kind.LINK
    if re.search(r"\{z\}.*\{[xy]\}", low) or "{quadkey}" in low:
        return Kind.XYZ
    q = query_dict(url)
    service = q.get("service", "").lower()
    if service in ("wms", "wfs", "wmts"):
        return {"wms": Kind.WMS, "wfs": Kind.WFS, "wmts": Kind.WMTS}[service]
    arc = arcgis_kind(url)
    if arc:
        return arc[0]
    ext = ext_of(url)
    if fmt in FORMAT_KINDS and FORMAT_KINDS[fmt]:
        kind = FORMAT_KINDS[fmt]
        if not low.startswith("http"):
            return Kind.LINK
        if kind in (Kind.VECTOR_FILE, Kind.COG) and (urlsplit(url).path.endswith("/") or not ext):
            return Kind.LINK  # a directory listing or landing page, not a file
        if kind == Kind.COG and ext not in (".tif", ".tiff"):
            return Kind.RASTER_FILE if ext in RASTER_EXT else Kind.LINK
        if kind == Kind.VECTOR_FILE and ext not in VECTOR_EXT | {".zip", ".kmz"}:
            return Kind.LINK
        return kind
    if "/wms" in low and fmt != "html":
        return Kind.WMS
    if "/wfs" in low and fmt != "html":
        return Kind.WFS
    if "wmts" in low and fmt != "html":
        return Kind.WMTS
    if ext == ".zip" and fmt in ("shp", "shapefile", "gpkg", "geojson", "kml", "fgdb", "gdb", "zip", ""):
        # zipped vector data is the common case in open-data portals
        return Kind.VECTOR_FILE if fmt in ("shp", "shapefile", "gpkg", "geojson", "kml", "fgdb", "gdb") else Kind.LINK
    if ext in RASTER_EXT:
        return Kind.COG if ext in (".tif", ".tiff") else Kind.RASTER_FILE
    if ext in VECTOR_EXT and ext not in (".json", ".csv"):
        return Kind.VECTOR_FILE
    if ext == ".json" and fmt == "geojson":
        return Kind.VECTOR_FILE
    return Kind.LINK


def gdal_path(url, kind=None):
    """GDAL virtual-filesystem path for streaming a remote file."""
    url = s3_to_https(url)
    if url.startswith("/vsi") or not url.lower().startswith(("http://", "https://")):
        return url
    ext = ext_of(url)
    if ext == ".zip":
        return "/vsizip//vsicurl/" + url
    if ext in (".gz",):
        return "/vsigzip//vsicurl/" + url
    if ext == ".kmz":
        return "/vsizip//vsicurl/" + url
    return "/vsicurl/" + url


def resource_from_url(url, name="", fmt=""):
    kind = guess_kind(url, fmt)
    layer = ""
    base = url
    if kind in (Kind.WMS, Kind.WFS, Kind.WMTS):
        q = query_dict(url)
        layer = q.get("layers") or q.get("typename") or q.get("typenames") or q.get("layer") or ""
        base = strip_query(url)
    elif kind in (Kind.ARCGIS_FEATURE, Kind.ARCGIS_MAP, Kind.ARCGIS_IMAGE):
        _, base, layer_id = arcgis_kind(url)
        layer = layer_id or ""
    return Resource(name=name or url, kind=kind, url=base, format=fmt, layer=layer)


# --------------------------------------------------------------------------- OWS capabilities

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _text(el, name, default=""):
    c = _child(el, name)
    return (c.text or "").strip() if c is not None and c.text else default


def detect_capabilities(xml_bytes):
    """Return 'wms', 'wfs', 'wmts' or None for a GetCapabilities document."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    tag = _local(root.tag).lower()
    if tag in ("wms_capabilities", "wmt_ms_capabilities"):
        return "wms"
    if tag == "wfs_capabilities":
        return "wfs"
    if tag == "capabilities" and "wmts" in root.tag.lower():
        return "wmts"
    return None


def parse_wms_capabilities(xml_bytes):
    """List of dicts: name, title, abstract, crs (list), bbox (lon/lat), styles."""
    root = ET.fromstring(xml_bytes)
    out = []

    def walk(layer, inherited_crs):
        crs = inherited_crs + [c.text.strip() for c in layer if _local(c.tag) in ("CRS", "SRS") and c.text]
        name = _text(layer, "Name")
        bbox = None
        geo = _child(layer, "EX_GeographicBoundingBox")
        if geo is not None:
            try:
                bbox = tuple(float(_text(geo, k)) for k in
                             ("westBoundLongitude", "southBoundLatitude", "eastBoundLongitude", "northBoundLatitude"))
            except ValueError:
                bbox = None
        else:
            ll = _child(layer, "LatLonBoundingBox")
            if ll is not None:
                try:
                    bbox = tuple(float(ll.get(k)) for k in ("minx", "miny", "maxx", "maxy"))
                except (TypeError, ValueError):
                    bbox = None
        if name:
            out.append({
                "name": name,
                "title": _text(layer, "Title") or name,
                "abstract": _text(layer, "Abstract"),
                "crs": sorted(set(crs)),
                "bbox": bbox,
                "styles": [_text(s, "Name") for s in _children(layer, "Style")],
            })
        for sub in _children(layer, "Layer"):
            walk(sub, crs)

    cap = _child(root, "Capability")
    if cap is not None:
        for layer in _children(cap, "Layer"):
            walk(layer, [])
    return out


def parse_wfs_capabilities(xml_bytes):
    """List of dicts: name, title, abstract, crs, bbox."""
    root = ET.fromstring(xml_bytes)
    out = []
    ftl = _child(root, "FeatureTypeList")
    if ftl is None:
        return out
    for ft in _children(ftl, "FeatureType"):
        name = _text(ft, "Name")
        if not name:
            continue
        crs = _text(ft, "DefaultCRS") or _text(ft, "DefaultSRS") or _text(ft, "SRS")
        bbox = None
        wgs = _child(ft, "WGS84BoundingBox")
        if wgs is not None:
            try:
                lo = [float(v) for v in _text(wgs, "LowerCorner").split()]
                hi = [float(v) for v in _text(wgs, "UpperCorner").split()]
                bbox = (lo[0], lo[1], hi[0], hi[1])
            except (ValueError, IndexError):
                bbox = None
        out.append({"name": name, "title": _text(ft, "Title") or name,
                    "abstract": _text(ft, "Abstract"), "crs": [crs] if crs else [], "bbox": bbox})
    return out


def parse_wmts_capabilities(xml_bytes):
    """List of dicts: name (identifier), title, formats, tile_matrix_sets, styles."""
    root = ET.fromstring(xml_bytes)
    out = []
    contents = _child(root, "Contents")
    if contents is None:
        return out
    for layer in _children(contents, "Layer"):
        ident = _text(layer, "Identifier")
        tms = [_text(l, "TileMatrixSet") for l in _children(layer, "TileMatrixSetLink")]
        out.append({
            "name": ident,
            "title": _text(layer, "Title") or ident,
            "abstract": _text(layer, "Abstract"),
            "formats": [f.text for f in _children(layer, "Format") if f.text],
            "tile_matrix_sets": tms,
            "styles": [_text(s, "Identifier") for s in _children(layer, "Style")],
        })
    return out


def pick_crs(available, preferred):
    """Pick a CRS a server supports, preferring the project CRS."""
    avail = [a.upper() for a in available or []]
    for c in [preferred, "EPSG:3857", "EPSG:900913", "EPSG:4326", "CRS:84"]:
        if c and c.upper() in avail:
            return c.upper() if c.upper() != "CRS:84" else "EPSG:4326"
    return (available[0] if available else preferred) or "EPSG:4326"
