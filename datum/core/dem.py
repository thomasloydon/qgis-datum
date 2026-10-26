# SPDX-License-Identifier: GPL-2.0-or-later
"""Elevation sources and the DEM builder.

The builder finds the tiles covering an area of interest through STAC, then
either streams them (a VRT pointing at the remote COGs) or clips, mosaics and
reprojects them into a local GeoTIFF, optionally producing hillshade, slope,
aspect, roughness and contours.

The GDAL work runs in a background QgsTask; this module only needs ``osgeo``
and is driven through a tiny ``feedback`` protocol (``canceled()``,
``progress(pct)``, ``log(msg)``) so it can be tested outside QGIS.
"""

import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import BBox, bbox_intersects

CANADA = (-141.1, 41.6, -52.5, 83.2)
CONUS_AK_HI = (-180.0, 17.0, -65.0, 72.0)
GLOBAL = (-180.0, -90.0, 180.0, 90.0)


@dataclass
class DemSource:
    id: str
    title: str
    provider: str            # provider id in the registry
    collection: str
    assets: Dict[str, str]   # surface ('dtm' / 'dsm') -> STAC asset key
    resolution: float        # metres
    coverage: BBox
    coverage_label: str
    description: str = ""
    license: str = ""
    item_props: Dict[str, object] = field(default_factory=dict)  # client-side property filter
    multi_project: bool = False   # overlapping items (lidar projects) rather than a tiled mosaic

    @property
    def surfaces(self):
        return list(self.assets)


DEM_SOURCES: List[DemSource] = [
    DemSource("hrdem-mosaic-1m", "HRDEM mosaic 1 m (NRCan lidar)", "nrcan_stac", "hrdem-mosaic-1m",
              {"dtm": "dtm", "dsm": "dsm"}, 1, CANADA, "Canada (lidar areas)",
              "High Resolution DEM mosaic from airborne lidar. Bare earth (DTM) and surface (DSM).",
              "Open Government Licence - Canada"),
    DemSource("hrdem-mosaic-2m", "HRDEM mosaic 2 m (NRCan lidar)", "nrcan_stac", "hrdem-mosaic-2m",
              {"dtm": "dtm", "dsm": "dsm"}, 2, CANADA, "Canada (lidar areas)",
              "HRDEM mosaic resampled to 2 m; lighter than the 1 m product.",
              "Open Government Licence - Canada"),
    DemSource("hrdem-lidar", "HRDEM by lidar project (NRCan)", "nrcan_stac", "hrdem-lidar",
              {"dtm": "dtm", "dsm": "dsm"}, 1, CANADA, "Canada (lidar projects)",
              "Individual lidar acquisitions, so you can pick a specific survey year.",
              "Open Government Licence - Canada", multi_project=True),
    DemSource("mrdem-30", "MRDEM 30 m (NRCan)", "nrcan_stac", "mrdem-30",
              {"dtm": "dtm", "dsm": "dsm"}, 30, CANADA, "Canada",
              "Medium Resolution DEM: seamless national 30 m terrain and surface models (2024+).",
              "Open Government Licence - Canada"),
    DemSource("cdem", "CDEM ~20 m (NRCan, legacy)", "nrcan_stac", "cdem",
              {"dtm": "dem"}, 20, CANADA, "Canada",
              "Canadian Digital Elevation Model. Superseded by MRDEM, kept for compatibility.",
              "Open Government Licence - Canada"),
    DemSource("3dep-seamless-10m", "USGS 3DEP 1/3 arc-second (~10 m)", "planetary", "3dep-seamless",
              {"dtm": "data"}, 10, CONUS_AK_HI, "United States",
              "USGS 3D Elevation Program seamless DEM.", "Public domain",
              item_props={"gsd": 10}),
    DemSource("3dep-lidar-dtm", "USGS 3DEP lidar DTM (2 m)", "planetary", "3dep-lidar-dtm",
              {"dtm": "data"}, 2, CONUS_AK_HI, "United States (lidar areas)",
              "Bare-earth DTM derived from 3DEP lidar point clouds.", "Public domain"),
    DemSource("3dep-lidar-dsm", "USGS 3DEP lidar DSM (2 m)", "planetary", "3dep-lidar-dsm",
              {"dsm": "data"}, 2, CONUS_AK_HI, "United States (lidar areas)",
              "First-return surface model derived from 3DEP lidar point clouds.", "Public domain"),
    DemSource("cop-dem-glo-30", "Copernicus GLO-30 (30 m)", "earth_search", "cop-dem-glo-30",
              {"dsm": "data"}, 30, GLOBAL, "Global",
              "Copernicus DEM: global 30 m surface model from TanDEM-X.", "Copernicus DEM licence (free)"),
    DemSource("cop-dem-glo-90", "Copernicus GLO-90 (90 m)", "earth_search", "cop-dem-glo-90",
              {"dsm": "data"}, 90, GLOBAL, "Global",
              "Copernicus DEM at 90 m: quick regional context.", "Copernicus DEM licence (free)"),
    DemSource("nasadem", "NASADEM (30 m)", "planetary", "nasadem",
              {"dsm": "elevation"}, 30, (-180, -56, 180, 61), "Global (56°S–60°N)",
              "Reprocessed SRTM elevation.", "Public domain"),
    DemSource("alos-dem", "ALOS World 3D (30 m)", "planetary", "alos-dem",
              {"dsm": "data"}, 30, GLOBAL, "Global",
              "JAXA ALOS AW3D30 surface model.", "JAXA terms (free)"),
]

SOURCES_BY_ID = {s.id: s for s in DEM_SOURCES}
AUTO = "auto"
# Finest first. Each is tried until one actually has data in the AOI.
AUTO_ORDER = ["hrdem-mosaic-1m", "mrdem-30", "3dep-seamless-10m", "cop-dem-glo-30"]

RESAMPLING = ["bilinear", "cubic", "near", "average", "cubicspline", "lanczos"]
COMPRESSION = ["DEFLATE", "LZW", "ZSTD", "NONE"]


# --------------------------------------------------------------------------- planning helpers

def candidate_sources(bbox_ll: BBox, surface: str):
    """AUTO_ORDER sources covering the AOI; those offering ``surface`` come first."""
    covering = [SOURCES_BY_ID[sid] for sid in AUTO_ORDER
                if bbox_intersects(SOURCES_BY_ID[sid].coverage, bbox_ll)]
    return [s for s in covering if surface in s.assets] + [s for s in covering if surface not in s.assets]


def asset_for(source: DemSource, surface: str):
    if surface in source.assets:
        return source.assets[surface], surface
    other = next(iter(source.assets))
    return source.assets[other], other


def bbox_area_km2(bbox_ll: BBox):
    """Approximate area of a lon/lat box."""
    lat = math.radians((bbox_ll[1] + bbox_ll[3]) / 2)
    w = (bbox_ll[2] - bbox_ll[0]) * 111.32 * math.cos(lat)
    h = (bbox_ll[3] - bbox_ll[1]) * 110.57
    return max(0.0, w) * max(0.0, h)


def estimate_mb(area_km2: float, resolution_m: float, bytes_per_px=4):
    px = area_km2 * 1e6 / (resolution_m ** 2)
    return px * bytes_per_px / 1e6


def overview_factor(area_km2: float, resolution_m: float, max_mb: float, max_factor=1024):
    """Smallest power of two the native resolution must be multiplied by to fit ``max_mb``.

    Powers of two line up with COG overview levels, so GDAL can read a small overview
    instead of decimating the full-resolution data (much faster over large areas).
    """
    f = 1
    while f < max_factor and estimate_mb(area_km2, resolution_m * f) > max_mb:
        f *= 2
    return f


def fit_resolution(area_km2: float, resolution_m: float, max_mb: float):
    """Coarsen the native resolution to an overview level until the estimate fits ``max_mb``."""
    return float(resolution_m * overview_factor(area_km2, resolution_m, max_mb))


def haversine_m(lon1, lat1, lon2, lat2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def units_per_metre(crs_wkt, bounds):
    """How many CRS units make one real metre at the centre of ``bounds``.

    Web Mercator "metres" are stretched by 1/cos(lat) (≈1.55 at 50°N), so using a
    metre resolution directly would produce ~2.4x the pixels the size budget expects.
    """
    from osgeo import osr
    src = osr.SpatialReference(wkt=crs_wkt)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
    if src.IsGeographic():
        return 1 / 110574.0
    wgs = osr.SpatialReference()
    wgs.ImportFromEPSG(4326)
    wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, wgs)
    d = max((bounds[2] - bounds[0]) / 100.0, 1.0)
    lon1, lat1, _ = ct.TransformPoint(cx - d / 2, cy)
    lon2, lat2, _ = ct.TransformPoint(cx + d / 2, cy)
    dist = haversine_m(lon1, lat1, lon2, lat2)
    return d / dist if dist > 0 else 1.0


def filter_items(items, source: DemSource):
    out = []
    for it in items:
        props = it.get("properties", {})
        if all(props.get(k) == v for k, v in source.item_props.items()):
            out.append(it)
    return out


def safe_name(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")[:80] or "dem"


# --------------------------------------------------------------------------- request / result

@dataclass
class DemRequest:
    source_id: str                    # a DemSource id or AUTO
    surface: str                      # dtm | dsm
    bbox_ll: BBox                     # AOI in EPSG:4326, used for the STAC search
    target_crs_wkt: str               # output CRS
    target_bounds: Tuple[float, float, float, float]  # AOI in the output CRS
    target_is_geographic: bool = False
    resolution: Optional[float] = None    # metres; None = native (or fitted to max_mb)
    resampling: str = "bilinear"
    mode: str = "download"            # download | stream
    out_dir: str = ""
    name: str = ""
    compression: str = "DEFLATE"
    max_mb: float = 500.0
    lidar_strategy: str = "newest"    # newest | mosaic  (for multi-project sources)
    hillshade: bool = False
    hillshade_multi: bool = True
    z_factor: float = 1.0
    slope: bool = False
    slope_percent: bool = False
    aspect: bool = False
    roughness: bool = False
    tri: bool = False
    tpi: bool = False
    contours: bool = False
    contour_interval: float = 10.0


@dataclass
class DemResult:
    source: Optional[DemSource] = None
    surface: str = ""
    dem_path: str = ""
    streamed: bool = False
    resolution: float = 0.0
    tiles: int = 0
    outputs: Dict[str, str] = field(default_factory=dict)  # derivative name -> path
    messages: List[str] = field(default_factory=list)


class Canceled(Exception):
    pass


class _NullFeedback:
    def canceled(self):
        return False

    def progress(self, pct):
        pass

    def log(self, msg):
        pass


# --------------------------------------------------------------------------- the builder

class DemBuilder:
    def __init__(self, registry, feedback=None):
        self.registry = registry   # provider id -> StacProvider
        self.fb = feedback or _NullFeedback()

    def _check(self):
        if self.fb.canceled():
            raise Canceled()

    def _gdal_progress(self, start, end):
        def cb(complete, message, data):
            self.fb.progress(start + (end - start) * complete)
            return 0 if self.fb.canceled() else 1
        return cb

    # -------------------------------------------------------------- find tiles
    def find_tiles(self, source: DemSource, surface: str, bbox_ll: BBox, strategy="newest"):
        provider = self.registry[source.provider]
        items = provider.search_items(source.collection, bbox_ll, limit=200)
        items = filter_items(items, source)
        if not items:
            return [], surface
        key, used_surface = asset_for(source, surface)
        if source.multi_project:
            items.sort(key=lambda i: i.get("properties", {}).get("datetime") or "")
            if strategy == "newest":
                items = items[-1:]
            # for "mosaic" the newest goes last so it ends up on top in the VRT
        hrefs = [provider.asset_href(it, key) for it in items]
        hrefs = [h for h in hrefs if h]
        return hrefs, used_surface

    # -------------------------------------------------------------- main entry
    def run(self, req: DemRequest) -> DemResult:
        from osgeo import gdal
        gdal.UseExceptions()
        for k, v in {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
                     "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff,.vrt,.TIF",
                     "GDAL_HTTP_MULTIRANGE": "YES", "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
                     "VSI_CACHE": "TRUE", "GDAL_HTTP_MAX_RETRY": "3", "GDAL_HTTP_RETRY_DELAY": "1",
                     "GDAL_HTTP_VERSION": "2", "GDAL_HTTP_MULTIPLEX": "YES", "GDAL_NUM_THREADS": "ALL_CPUS",
                     "GDAL_CACHEMAX": "512"}.items():
            gdal.SetThreadLocalConfigOption(k, v)

        result = DemResult()
        os.makedirs(req.out_dir, exist_ok=True)
        if req.source_id == AUTO:
            sources = candidate_sources(req.bbox_ll, req.surface)
        else:
            sources = [SOURCES_BY_ID[req.source_id]]
        if not sources:
            raise RuntimeError("No elevation source covers this area.")

        area = bbox_area_km2(req.bbox_ll)
        if req.source_id == AUTO and not req.resolution:
            # Don't mosaic hundreds of 1 m lidar tiles just to resample them to 30 m+.
            sources = [s for s in sources[:-1] if fit_resolution(area, s.resolution, req.max_mb) < 10 * s.resolution] \
                + sources[-1:]
        chosen = None
        for i, src in enumerate(sources):
            self._check()
            self.fb.log(f"Searching {src.title}…")
            hrefs, surface = self.find_tiles(src, req.surface, req.bbox_ll, req.lidar_strategy)
            if not hrefs:
                self.fb.log(f"  no tiles from {src.title}")
                continue
            vsis = ["/vsicurl/" + h for h in hrefs]
            if req.source_id == AUTO and i < len(sources) - 1 and not self._has_data(vsis, req):
                self.fb.log(f"  {src.title} has no data here, trying the next source")
                continue
            chosen = (src, surface, vsis)
            break
        if not chosen:
            raise RuntimeError("No elevation tiles were found for this area.")

        src, surface, vsis = chosen
        result.source, result.surface, result.tiles = src, surface, len(vsis)
        if surface != req.surface:
            result.messages.append(f"{src.title} only provides a {surface.upper()}; used that instead.")
        self.fb.log(f"Using {src.title} ({len(vsis)} tile{'s' if len(vsis) != 1 else ''})")
        self.fb.progress(10)

        base = safe_name(req.name or f"{src.id}_{surface}")
        mosaic_vrt = os.path.join(req.out_dir, f"{base}_sources.vrt")
        gdal.BuildVRT(mosaic_vrt, vsis, resampleAlg=req.resampling)
        self._check()

        res_m = req.resolution or src.resolution
        factor = 1
        if not req.resolution:
            factor = overview_factor(area, src.resolution, req.max_mb)
            fitted = fit_resolution(area, src.resolution, req.max_mb)
            if fitted != src.resolution:
                result.messages.append(
                    f"Native {src.resolution:g} m would be ~{estimate_mb(area, src.resolution):,.0f} MB; "
                    f"resampled to {fitted:g} m to stay under {req.max_mb:,.0f} MB.")
            res_m = fitted
        result.resolution = res_m
        res = res_m * units_per_metre(req.target_crs_wkt, req.target_bounds)

        warp_kw = dict(
            dstSRS=req.target_crs_wkt, outputBounds=req.target_bounds, xRes=res, yRes=res,
            resampleAlg=req.resampling, targetAlignedPixels=True, multithread=True,
            warpMemoryLimit=512 * 1024 * 1024, warpOptions=["NUM_THREADS=ALL_CPUS"],
            dstNodata=-32767, outputType=gdal.GDT_Float32,
        )

        if req.mode == "stream":
            out = os.path.join(req.out_dir, f"{base}.vrt")
            gdal.Warp(out, mosaic_vrt, format="VRT", **warp_kw)
            result.dem_path, result.streamed = out, True
            self.fb.progress(100)
            return result

        out = self._unique(os.path.join(req.out_dir, f"{base}.tif"))
        opts = ["TILED=YES", "BIGTIFF=IF_SAFER", "NUM_THREADS=ALL_CPUS"]
        if req.compression != "NONE":
            opts += [f"COMPRESS={req.compression}", "PREDICTOR=3"]
        self.fb.log("Downloading and clipping…")
        if factor > 1:
            # read overview n directly (overview 0 is 2x, 1 is 4x, ...); GDAL's AUTO choice
            # misses it whenever the target is a hair finer, e.g. after reprojection
            warp_kw["overviewLevel"] = str(int(math.log2(factor)) - 1)
        try:
            gdal.Warp(out, mosaic_vrt, format="GTiff", creationOptions=opts,
                      callback=self._gdal_progress(10, 70), **warp_kw)
        except RuntimeError as e:
            if "overviewLevel" not in warp_kw or self.fb.canceled():
                raise
            self.fb.log(f"  overview read failed ({e}); reading full resolution")
            warp_kw.pop("overviewLevel")
            gdal.Warp(out, mosaic_vrt, format="GTiff", creationOptions=opts,
                      callback=self._gdal_progress(10, 70), **warp_kw)
        self._check()
        try:
            os.remove(mosaic_vrt)
        except OSError:
            pass
        result.dem_path = out
        self._derivatives(req, result, opts)
        self.fb.progress(100)
        return result

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _unique(path):
        if not os.path.exists(path):
            return path
        root, ext = os.path.splitext(path)
        n = 2
        while os.path.exists(f"{root}_{n}{ext}"):
            n += 1
        return f"{root}_{n}{ext}"

    def _has_data(self, vsis, req, min_valid=0.5):
        """Cheap coverage probe: warp the AOI to a 64x64 grid and count valid cells."""
        from osgeo import gdal
        import array
        try:
            src = gdal.BuildVRT("", vsis)
            ds = gdal.Warp("", src, format="MEM", dstSRS="EPSG:4326", outputBounds=req.bbox_ll,
                           width=64, height=64, dstNodata=-32767, outputType=gdal.GDT_Float32)
            band = ds.GetRasterBand(1)
            raw = band.ReadRaster(0, 0, 64, 64, buf_type=gdal.GDT_Float32)
            vals = array.array("f", raw)
            nodata = {-32767.0, -9999.0, -3.4028234663852886e38}
            src_nd = src.GetRasterBand(1).GetNoDataValue()
            if src_nd is not None:
                nodata.add(float(src_nd))
            valid = sum(1 for v in vals if v == v and v not in nodata and v > -1e30)
            return valid / len(vals) >= min_valid
        except RuntimeError as e:
            self.fb.log(f"  coverage probe failed: {e}")
            return False

    def _derivatives(self, req: DemRequest, result: DemResult, opts):
        from osgeo import gdal
        root, _ = os.path.splitext(result.dem_path)
        scale = 111120 if req.target_is_geographic else 1
        jobs = []
        if req.hillshade:
            jobs.append(("hillshade", "hillshade", dict(multiDirectional=req.hillshade_multi,
                                                        zFactor=req.z_factor, scale=scale)))
        if req.slope:
            jobs.append(("slope", "slope", dict(slopeFormat="percent" if req.slope_percent else "degree",
                                                scale=scale)))
        if req.aspect:
            jobs.append(("aspect", "aspect", dict(zeroForFlat=True)))
        if req.roughness:
            jobs.append(("roughness", "Roughness", {}))
        if req.tri:
            jobs.append(("tri", "TRI", {}))
        if req.tpi:
            jobs.append(("tpi", "TPI", {}))
        total = len(jobs) + (1 if req.contours else 0)
        step = 30.0 / max(total, 1)
        pct = 70.0
        for name, mode, kw in jobs:
            self._check()
            self.fb.log(f"Computing {name}…")
            out = f"{root}_{name}.tif"
            # hillshade is 8-bit: the floating-point predictor would be rejected
            job_opts = [o.replace("PREDICTOR=3", "PREDICTOR=2") for o in opts] if name == "hillshade" else opts
            gdal.DEMProcessing(out, result.dem_path, mode, format="GTiff", creationOptions=job_opts,
                               computeEdges=True, callback=self._gdal_progress(pct, pct + step), **kw)
            result.outputs[name] = out
            pct += step
        if req.contours:
            self._check()
            self.fb.log("Generating contours…")
            result.outputs["contours"] = self._contours(result.dem_path, f"{root}_contours.gpkg",
                                                        req.contour_interval, pct, pct + step)

    def _contours(self, dem_path, out_path, interval, p0, p1):
        from osgeo import gdal, ogr, osr
        ds = gdal.Open(dem_path)
        band = ds.GetRasterBand(1)
        drv = ogr.GetDriverByName("GPKG")
        if os.path.exists(out_path):
            drv.DeleteDataSource(out_path)
        out = drv.CreateDataSource(out_path)
        srs = osr.SpatialReference(wkt=ds.GetProjection())
        lyr = out.CreateLayer("contours", srs, ogr.wkbLineString)
        lyr.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
        lyr.CreateField(ogr.FieldDefn("elev", ogr.OFTReal))
        nd = band.GetNoDataValue()
        opts = [f"LEVEL_INTERVAL={interval}", "ID_FIELD=0", "ELEV_FIELD=1"]
        if nd is not None:
            opts.append(f"NODATA={nd}")
        gdal.ContourGenerateEx(band, lyr, options=opts, callback=self._gdal_progress(p0, p1))
        out = None  # flush
        ds = None
        return out_path
