# SPDX-License-Identifier: GPL-2.0-or-later
"""CKAN open-data portals (BC Data Catalogue, Open Government Canada, any custom portal)."""

import html
import json
import re

from ..models import Dataset, Resource, Kind, SearchPage, SearchQuery
from ..sniff import resource_from_url, LINK_FORMATS
from .base import Provider

SORTS = {
    "relevance": "score desc, metadata_modified desc",
    "updated": "metadata_modified desc",
    "title": "title_string asc",
}

# Kind -> res_format values to OR together in the ``fq`` filter
DEFAULT_FORMAT_MAP = {
    Kind.WMS: ["WMS", "wms"],
    Kind.WFS: ["WFS", "wfs"],
    Kind.WMTS: ["WMTS", "wmts"],
    Kind.ARCGIS_FEATURE: ["ESRI REST", "esri rest", "Esri REST"],
    Kind.ARCGIS_MAP: ["ESRI REST", "esri rest", "Esri REST"],
    Kind.VECTOR_FILE: ["GeoJSON", "geojson", "KML", "kml", "SHP", "shp", "GPKG", "gpkg", "FGDB/GDB", "fgdb"],
    Kind.COG: ["GeoTIFF", "geotiff", "TIFF", "tiff", "COG"],
}


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def bbox_from_geojson(geom):
    """Lon/lat bbox of a GeoJSON geometry (dict or JSON string)."""
    if not geom:
        return None
    if isinstance(geom, str):
        try:
            geom = json.loads(geom)
        except ValueError:
            return None
    xs, ys = [], []

    def walk(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        elif isinstance(c, (list, tuple)):
            for i in c:
                walk(i)

    walk(geom.get("coordinates") if isinstance(geom, dict) else None)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


class CkanProvider(Provider):
    family = "ckan"
    supports_org = True

    def __init__(self, pid, label, base_url, http=None, lang="en", supports_bbox=False,
                 description="", coverage="", format_map=None):
        super().__init__(http)
        self.id = pid
        self.label = label
        self.base_url = base_url.rstrip("/")
        self.lang = lang
        self.supports_bbox = supports_bbox
        self.description = description
        self.coverage = coverage
        self.homepage = self.base_url
        self.format_map = format_map or DEFAULT_FORMAT_MAP

    @property
    def api(self):
        return f"{self.base_url}/api/3/action"

    # ------------------------------------------------------------------ search
    def build_params(self, query: SearchQuery):
        fq = []
        if query.organization:
            fq.append(f'organization:"{query.organization}"')
        fmts = []
        for kind in query.formats:
            fmts += [f for f in self.format_map.get(kind, []) if f not in fmts]
        if fmts:
            fq.append("res_format:(" + " OR ".join(f'"{f}"' for f in fmts) + ")")
        params = {
            "q": query.text or "*:*",
            "rows": query.limit,
            "start": query.offset,
            "sort": SORTS.get(query.sort, SORTS["relevance"]),
            "facet.field": json.dumps(["organization", "res_format"]),
            "facet.limit": 50,
        }
        if fq:
            params["fq"] = " AND ".join(fq)
        if query.bbox and self.supports_bbox:
            params["ext_bbox"] = ",".join(f"{v:.5f}" for v in query.bbox)
        return params

    def search(self, query: SearchQuery) -> SearchPage:
        data = self.http(f"{self.api}/package_search", params=self.build_params(query))
        result = data.get("result", data)
        datasets = [self.parse_package(p) for p in result.get("results", [])]
        facets = {}
        for name, facet in (result.get("search_facets") or {}).items():
            items = [(i["name"], self.localize(i.get("display_name") or i["name"]), i.get("count", 0))
                     for i in facet.get("items", [])]
            facets[name] = sorted(items, key=lambda t: -t[2])
        return SearchPage(datasets=datasets, total=result.get("count"), offset=query.offset, facets=facets)

    # ------------------------------------------------------------------ parsing
    def localize(self, value):
        """Handle the bilingual conventions of Canadian portals."""
        if isinstance(value, dict):
            return value.get(self.lang) or value.get("en") or next(iter(value.values()), "")
        if isinstance(value, str) and " | " in value:
            en, _, fr = value.partition(" | ")
            return fr if self.lang == "fr" else en
        return value or ""

    def parse_package(self, p) -> Dataset:
        title = self.localize(p.get("title_translated") or p.get("title") or p.get("name"))
        notes = self.localize(p.get("notes_translated") or p.get("notes") or "")
        org = p.get("organization") or {}
        tags = [self.localize(t.get("display_name") or t.get("name")) for t in p.get("tags", [])]
        if isinstance(p.get("keywords"), dict):
            tags = p["keywords"].get(self.lang) or p["keywords"].get("en") or tags
        ds = Dataset(
            id=p.get("id") or p.get("name"),
            title=title,
            source=self.id,
            source_label=self.label,
            description=strip_html(notes),
            organization=self.localize(org.get("title") or org.get("name") or ""),
            page_url=f"{self.base_url}/dataset/{p.get('name') or p.get('id')}",
            tags=[t for t in tags if t],
            license=p.get("license_title") or p.get("license_id") or "",
            updated=(p.get("metadata_modified") or "")[:10],
            bbox=bbox_from_geojson(p.get("spatial")),
            extra={"name": p.get("name"), "org_name": org.get("name", "")},
        )
        ds.resources = self.parse_resources(p)
        return ds

    def parse_resources(self, p):
        out = []
        for r in p.get("resources", []):
            langs = r.get("language") or []
            if isinstance(langs, list) and langs and self.lang not in langs and "zxx" not in langs:
                continue  # bilingual portals publish one copy of each service per language
            url = (r.get("url") or "").strip()
            fmt = (r.get("format") or "").strip()
            name = self.localize(r.get("name_translated") or r.get("name") or fmt or "Resource")
            if fmt.lower() in LINK_FORMATS:
                out.append(Resource(name=name, kind=Kind.LINK, url=url, format=fmt))
                continue
            res = resource_from_url(url, name=name, fmt=fmt)
            out.append(res)
        return out


class BCDataCatalogue(CkanProvider):
    """BC Data Catalogue: most spatial records are served by the openmaps GeoServer."""

    WFS_URL = "https://openmaps.gov.bc.ca/geo/pub/wfs"
    WMS_URL = "https://openmaps.gov.bc.ca/geo/pub/wms"

    def __init__(self, http=None):
        fmap = dict(DEFAULT_FORMAT_MAP)
        # every openmaps layer exposes WMS + WFS, but CKAN only records "wms"
        fmap[Kind.WFS] = ["wms", "WMS"]
        super().__init__(
            "bcdc", "BC Data Catalogue", "https://catalogue.data.gov.bc.ca", http=http,
            description="Province of British Columbia open data: 2,000+ layers served live from the "
                        "BC Geographic Warehouse (WFS/WMS), plus downloads.",
            coverage="British Columbia", format_map=fmap)

    def parse_resources(self, p):
        objects = []
        others = []
        for r in p.get("resources", []):
            obj = r.get("object_name")
            url = (r.get("url") or "").strip()
            fmt = (r.get("format") or "").strip()
            if obj:
                if obj not in objects:
                    objects.append(obj)
                if fmt.lower() in ("wms", "kml"):
                    continue  # replaced by the canonical WFS/WMS resources below
            name = r.get("name") or fmt or "Resource"
            if fmt.lower() in ("multiple", "oracle_sde", "other") or fmt.lower() in LINK_FORMATS:
                others.append(Resource(name=name, kind=Kind.LINK, url=url, format=fmt))
            else:
                others.append(resource_from_url(url, name=name, fmt=fmt))
        out = []
        for obj in objects:
            short = obj.split(".")[-1]
            out.append(Resource(name=f"{short} (live features)", kind=Kind.WFS, url=self.WFS_URL,
                                format="WFS", layer=f"pub:{obj}", crs="EPSG:3005",
                                extra={"object_name": obj}))
            out.append(Resource(name=f"{short} (map image)", kind=Kind.WMS, url=self.WMS_URL,
                                format="WMS", layer=f"pub:{obj}", extra={"object_name": obj}))
        return out + others


class OpenCanada(CkanProvider):
    def __init__(self, http=None, lang="en"):
        super().__init__(
            "opencanada", "Open Government Canada", "https://open.canada.ca/data", http=http, lang=lang,
            supports_bbox=True,
            description="Federal open data (NRCan, ECCC, StatCan, ...) including CanVec, CanElevation, "
                        "hydrometric and land-cover products.",
            coverage="Canada")

    def parse_package(self, p):
        ds = super().parse_package(p)
        ds.page_url = f"https://open.canada.ca/data/{self.lang}/dataset/{p.get('id')}"
        return ds
