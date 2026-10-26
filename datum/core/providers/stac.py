# SPDX-License-Identifier: GPL-2.0-or-later
"""STAC APIs: NRCan GEO.ca datacube, Element 84 Earth Search, Microsoft Planetary Computer."""

import threading
import time

from ..models import Dataset, Resource, Kind, SearchPage, SearchQuery, bbox_intersects
from ..sniff import s3_to_https
from .base import Provider

RASTER_TYPES = ("image/tiff", "image/vnd.stac.geotiff", "application/x-geotiff", "image/jp2")


def is_raster_asset(asset):
    t = (asset.get("type") or "").lower()
    href = asset.get("href", "").lower()
    roles = asset.get("roles") or []
    if "thumbnail" in roles or "overview" in roles:
        return False
    return t.startswith(RASTER_TYPES) or href.endswith((".tif", ".tiff", ".jp2"))


class StacProvider(Provider):
    family = "stac"

    def __init__(self, pid, label, url, http=None, description="", coverage="", signer=None,
                 hidden_collections=()):
        super().__init__(http)
        self.id = pid
        self.label = label
        self.url = url.rstrip("/")
        self.homepage = self.url
        self.description = description
        self.coverage = coverage
        self.supports_bbox = True
        self.signer = signer
        self.hidden = set(hidden_collections)
        self._collections = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ collections
    def collections(self):
        with self._lock:
            if self._collections is None:
                data = self.http(f"{self.url}/collections")
                cols = data.get("collections", [])
                # follow pagination if the server uses it
                nxt = next((l["href"] for l in data.get("links", []) if l.get("rel") == "next"), None)
                guard = 0
                while nxt and guard < 20:
                    page = self.http(nxt)
                    cols += page.get("collections", [])
                    nxt = next((l["href"] for l in page.get("links", []) if l.get("rel") == "next"), None)
                    guard += 1
                self._collections = [c for c in cols if c.get("id") not in self.hidden]
            return self._collections

    def collection_dataset(self, c) -> Dataset:
        bbox = None
        try:
            b = c["extent"]["spatial"]["bbox"][0]
            bbox = (b[0], b[1], b[2], b[3]) if len(b) == 4 else (b[0], b[1], b[3], b[4])
        except (KeyError, IndexError, TypeError):
            pass
        interval = ""
        try:
            t0, t1 = c["extent"]["temporal"]["interval"][0]
            interval = f"{(t0 or '…')[:10]} → {(t1 or 'present')[:10]}"
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        thumb = ""
        for a in (c.get("assets") or {}).values():
            if "thumbnail" in (a.get("roles") or []):
                thumb = a.get("href", "")
        lic = c.get("license", "")
        providers = ", ".join(p.get("name", "") for p in c.get("providers", []) if p.get("name"))
        title = c.get("title") or c["id"]
        if " / " in title:  # NRCan titles are "English / Français"
            title = title.split(" / ")[0]
        desc = c.get("description") or ""
        return Dataset(
            id=c["id"],
            title=title,
            source=self.id,
            source_label=self.label,
            description=desc.split("\n\n")[0][:1500] if desc else "",
            organization=providers,
            page_url=next((l["href"] for l in c.get("links", []) if l.get("rel") in ("about", "license", "describedby")),
                          f"{self.url}/collections/{c['id']}"),
            tags=list(c.get("keywords") or [])[:12],
            license=lic,
            updated=interval,
            bbox=bbox,
            thumbnail=thumb,
            resources=[Resource(name=f"{title} (search imagery in extent)", kind=Kind.STAC_COLLECTION,
                                url=self.url, layer=c["id"], format="STAC",
                                extra={"provider": self.id})],
            extra={"item_assets": list((c.get("item_assets") or {}).keys())},
        )

    def search(self, query: SearchQuery) -> SearchPage:
        words = [w.lower() for w in (query.text or "").split() if w.strip()]
        matches = []
        for c in self.collections():
            hay = " ".join([c.get("id", ""), c.get("title", ""), c.get("description", ""),
                            " ".join(c.get("keywords") or [])]).lower()
            if words and not all(w in hay for w in words):
                continue
            ds = self.collection_dataset(c)
            if query.bbox and not bbox_intersects(ds.bbox, query.bbox):
                continue
            score = sum(3 for w in words if w in (c.get("title") or "").lower() or w in c["id"].lower())
            matches.append((score, ds))
        if query.formats and Kind.STAC_COLLECTION not in query.formats and Kind.COG not in query.formats:
            matches = []
        if query.sort == "title":
            matches.sort(key=lambda t: t[1].title.lower())
        else:
            matches.sort(key=lambda t: -t[0])
        page = [ds for _, ds in matches[query.offset:query.offset + query.limit]]
        return SearchPage(datasets=page, total=len(matches), offset=query.offset)

    # ------------------------------------------------------------------ items
    def search_items(self, collection, bbox, datetime=None, max_cloud=None, limit=50, query=None):
        """Return STAC item dicts intersecting ``bbox`` (lon/lat)."""
        body = {"collections": [collection], "bbox": list(bbox), "limit": min(limit, 100)}
        if datetime:
            body["datetime"] = datetime
        q = dict(query or {})
        if max_cloud is not None:
            q["eo:cloud_cover"] = {"lte": max_cloud}
        if q:
            body["query"] = q
        items = []
        url = f"{self.url}/search"
        data = self.http(url, data=body)
        guard = 0
        while True:
            items += data.get("features", [])
            nxt = next((l for l in data.get("links", []) if l.get("rel") == "next"), None)
            if not nxt or len(items) >= limit or guard > 20:
                break
            guard += 1
            if nxt.get("method", "GET").upper() == "POST":
                data = self.http(nxt["href"], data=nxt.get("body") or body)
            else:
                data = self.http(nxt["href"])
        return items[:limit]

    def asset_href(self, item, key):
        asset = item.get("assets", {}).get(key)
        if not asset:
            return None
        href = s3_to_https(asset["href"])
        if self.signer:
            href = self.signer(href, item.get("collection"))
        return href

    @staticmethod
    def raster_assets(item):
        return [k for k, a in item.get("assets", {}).items() if is_raster_asset(a)]


class PlanetaryComputerSigner:
    """Appends a short-lived SAS token to Planetary Computer blob URLs."""

    TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{collection}"

    def __init__(self, http):
        self.http = http
        self._tokens = {}
        self._lock = threading.Lock()

    def __call__(self, href, collection):
        if ".blob.core.windows.net" not in href or "?" in href or not collection:
            return href
        with self._lock:
            tok = self._tokens.get(collection)
            if not tok or tok[0] < time.time() + 300:
                data = self.http(self.TOKEN_URL.format(collection=collection), use_cache=False)
                # tokens are valid ~1h; refresh a little early
                tok = (time.time() + 45 * 60, data["token"])
                self._tokens[collection] = tok
        return f"{href}?{tok[1]}"


def nrcan_datacube(http=None):
    return StacProvider(
        "nrcan_stac", "NRCan GEO.ca Datacube", "https://datacube.services.geo.ca/stac/api", http=http,
        description="Natural Resources Canada analysis-ready rasters: MRDEM, HRDEM (lidar), CDEM, land cover, "
                    "surface water, air-photo series and more, all as cloud-optimised GeoTIFFs.",
        coverage="Canada")


def earth_search(http=None):
    return StacProvider(
        "earth_search", "Earth Search (AWS)", "https://earth-search.aws.element84.com/v1", http=http,
        description="Sentinel-2, Sentinel-1, Copernicus DEM and NAIP on AWS Open Data.",
        coverage="Global",
        hidden_collections=("landsat-c2-l2",))  # requester-pays bucket


def planetary_computer(http=None):
    from .. import net
    h = http or net.fetch_json
    return StacProvider(
        "planetary", "Microsoft Planetary Computer", "https://planetarycomputer.microsoft.com/api/stac/v1", http=h,
        description="130+ global datasets: USGS 3DEP lidar DEMs, NASADEM, ALOS, Landsat, Sentinel, ESA WorldCover, "
                    "land cover and climate. Assets are signed automatically.",
        coverage="Global", signer=PlanetaryComputerSigner(h))
