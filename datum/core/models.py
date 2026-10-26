# SPDX-License-Identifier: GPL-2.0-or-later
"""Plain data objects shared by providers, the loader and the UI.

Nothing in here imports QGIS so it can be unit tested with a stock Python.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple, List, Dict, Any

# A bounding box is always (min_lon, min_lat, max_lon, max_lat) in EPSG:4326.
BBox = Tuple[float, float, float, float]


class Kind:
    """How a resource can be brought into QGIS."""

    WMS = "wms"
    WMTS = "wmts"
    WFS = "wfs"
    XYZ = "xyz"
    ARCGIS_FEATURE = "arcgis_feature"
    ARCGIS_MAP = "arcgis_map"
    ARCGIS_IMAGE = "arcgis_image"
    COG = "cog"                    # cloud optimised / remote GeoTIFF, streamed via /vsicurl/
    RASTER_FILE = "raster_file"    # other remote raster formats
    VECTOR_FILE = "vector_file"    # GeoJSON, KML, GPKG, zipped shapefile, ...
    STAC_COLLECTION = "stac_collection"  # needs an AOI before anything can be added
    DEM = "dem"                    # handled by the Elevation builder
    LINK = "link"                  # web page / pdf: open in browser only

    ADDABLE = {WMS, WMTS, WFS, XYZ, ARCGIS_FEATURE, ARCGIS_MAP, ARCGIS_IMAGE,
               COG, RASTER_FILE, VECTOR_FILE, STAC_COLLECTION, DEM}

    LABELS = {
        WMS: "WMS", WMTS: "WMTS", WFS: "WFS", XYZ: "Tiles",
        ARCGIS_FEATURE: "ArcGIS Feature", ARCGIS_MAP: "ArcGIS Map",
        ARCGIS_IMAGE: "ArcGIS Image", COG: "COG", RASTER_FILE: "Raster",
        VECTOR_FILE: "Vector", STAC_COLLECTION: "STAC", DEM: "DEM", LINK: "Link",
    }

    # When a dataset has several resources, the one we pick for a
    # double-click "just add it" is the first kind found in this order.
    PREFERENCE = [DEM, WFS, ARCGIS_FEATURE, COG, VECTOR_FILE, WMS, WMTS,
                  ARCGIS_MAP, ARCGIS_IMAGE, XYZ, RASTER_FILE, STAC_COLLECTION]

    @classmethod
    def is_raster(cls, kind):
        return kind in {cls.WMS, cls.WMTS, cls.XYZ, cls.ARCGIS_MAP, cls.ARCGIS_IMAGE,
                        cls.COG, cls.RASTER_FILE, cls.DEM}


@dataclass
class Resource:
    name: str
    kind: str
    url: str
    format: str = ""
    layer: str = ""          # WMS layer, WFS typename, ArcGIS layer id, STAC collection id ...
    crs: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def addable(self):
        return self.kind in Kind.ADDABLE

    @property
    def label(self):
        return Kind.LABELS.get(self.kind, self.kind.upper())

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d.get(k) for k in ("name", "kind", "url", "format", "layer", "crs")
                      if d.get(k) is not None}, extra=d.get("extra") or {})


@dataclass
class Dataset:
    id: str
    title: str
    source: str                       # provider id
    source_label: str = ""
    description: str = ""
    organization: str = ""
    page_url: str = ""
    tags: List[str] = field(default_factory=list)
    license: str = ""
    updated: str = ""
    bbox: Optional[BBox] = None
    category: str = ""
    thumbnail: str = ""
    resources: List[Resource] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self):
        return f"{self.source}:{self.id}"

    @property
    def addable_resources(self):
        return [r for r in self.resources if r.addable]

    @property
    def kinds(self):
        seen = []
        for r in self.resources:
            if r.addable and r.kind not in seen:
                seen.append(r.kind)
        return seen

    def best_resource(self, prefer: Optional[List[str]] = None) -> Optional[Resource]:
        order = (prefer or []) + [k for k in Kind.PREFERENCE if k not in (prefer or [])]
        for kind in order:
            for r in self.resources:
                if r.kind == kind:
                    return r
        return None

    def to_dict(self):
        d = asdict(self)
        d["bbox"] = list(self.bbox) if self.bbox else None
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        res = [Resource.from_dict(r) for r in d.pop("resources", [])]
        bbox = d.pop("bbox", None)
        known = {f for f in cls.__dataclass_fields__}
        ds = cls(**{k: v for k, v in d.items() if k in known and k != "resources"})
        ds.resources = res
        ds.bbox = tuple(bbox) if bbox else None
        return ds


@dataclass
class SearchQuery:
    text: str = ""
    bbox: Optional[BBox] = None       # restrict to data intersecting this extent
    formats: List[str] = field(default_factory=list)   # Kind values; empty = any
    organization: str = ""
    sort: str = "relevance"           # relevance | updated | title
    offset: int = 0
    limit: int = 25


@dataclass
class SearchPage:
    datasets: List[Dataset]
    total: Optional[int] = None
    offset: int = 0
    facets: Dict[str, List[Tuple[str, str, int]]] = field(default_factory=dict)  # name -> [(value, label, count)]

    @property
    def has_more(self):
        return self.total is not None and self.offset + len(self.datasets) < self.total


def bbox_intersects(a: Optional[BBox], b: Optional[BBox]) -> bool:
    """True if two lon/lat boxes overlap. Unknown extents are treated as overlapping."""
    if not a or not b:
        return True
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])
