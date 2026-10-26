# SPDX-License-Identifier: GPL-2.0-or-later
"""Hand-picked, verified layers for the Quick Add tab (also searchable)."""

from .models import Dataset, Resource, Kind, SearchPage, SearchQuery, bbox_intersects
from .dem import CANADA, CONUS_AK_HI, GLOBAL
from .providers.base import Provider

BC = (-139.1, 48.2, -114.0, 60.0)
BC_WFS = "https://openmaps.gov.bc.ca/geo/pub/wfs"
DEM_COG = "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/"

ELEVATION = "Elevation & terrain"
BASEMAPS = "Basemaps"
IMAGERY = "Imagery"
HYDRO = "Water"
TRANSPORT = "Transportation"
ADMIN = "Boundaries & admin"
LAND = "Land & parcels"
ECOLOGY = "Forests & ecology"
HAZARDS = "Fire & hazards"
GEOLOGY = "Geology & mining"
PLACES = "Place names"

CATEGORY_ORDER = [ELEVATION, BASEMAPS, IMAGERY, HYDRO, TRANSPORT, ADMIN, LAND, ECOLOGY, HAZARDS, GEOLOGY, PLACES]
CATEGORY_ICONS = {
    ELEVATION: "mountain", BASEMAPS: "map", IMAGERY: "satellite", HYDRO: "water", TRANSPORT: "road",
    ADMIN: "boundary", LAND: "parcel", ECOLOGY: "tree", HAZARDS: "fire", GEOLOGY: "rock", PLACES: "pin",
}

COVERAGE_LABELS = {BC: "BC", CANADA: "Canada", CONUS_AK_HI: "USA", GLOBAL: "Global"}


def _entry(eid, title, category, coverage, description, resources, license="", tags=()):
    return Dataset(id=eid, title=title, source="curated", source_label="Quick picks", description=description,
                   category=category, bbox=coverage, resources=resources, license=license, tags=list(tags),
                   extra={"coverage": COVERAGE_LABELS.get(coverage, "")})


def _bc(eid, title, category, obj, description, tags=()):
    return _entry(eid, title, category, BC, description,
                  [Resource(title, Kind.WFS, BC_WFS, "WFS", f"pub:{obj}", "EPSG:3005", {"object_name": obj}),
                   Resource(title + " (map image)", Kind.WMS, "https://openmaps.gov.bc.ca/geo/pub/wms", "WMS",
                            f"pub:{obj}")],
                  license="Open Government Licence - British Columbia", tags=tags)


def _xyz(eid, title, category, url, description, coverage=GLOBAL, zmax=19, license="", attribution=""):
    return _entry(eid, title, category, coverage, description,
                  [Resource(title, Kind.XYZ, url, "XYZ", extra={"zmax": zmax, "attribution": attribution})],
                  license=license)


def _dem(eid, title, source_id, coverage, description, license=""):
    return _entry(eid, title, ELEVATION, coverage, description,
                  [Resource(title, Kind.DEM, "", "DEM", source_id)], license=license,
                  tags=["dem", "elevation", "terrain"])


ENTRIES = [
    # ---------------------------------------------------------------- elevation
    _dem("dem-auto", "Best available DEM for the map extent", "auto", GLOBAL,
         "Picks the finest elevation model with data in view: HRDEM 1 m lidar → MRDEM 30 m in Canada, "
         "USGS 3DEP 10 m in the US, Copernicus 30 m elsewhere. Clipped to the extent."),
    _entry("mrdem-dtm", "MRDEM 30 m bare-earth DTM (all of Canada, streamed)", ELEVATION, CANADA,
           "Seamless national terrain model, streamed as a cloud-optimised GeoTIFF. Nothing is downloaded "
           "until you look at it.",
           [Resource("MRDEM 30 m DTM", Kind.COG, DEM_COG + "mrdem-30-dtm.tif", "COG", extra={"style": "elevation"})],
           license="Open Government Licence - Canada", tags=["dem", "dtm"]),
    _entry("mrdem-dsm", "MRDEM 30 m surface DSM (all of Canada, streamed)", ELEVATION, CANADA,
           "Surface model including vegetation and buildings.",
           [Resource("MRDEM 30 m DSM", Kind.COG, DEM_COG + "mrdem-30-dsm.tif", "COG", extra={"style": "elevation"})],
           license="Open Government Licence - Canada", tags=["dem", "dsm"]),
    _entry("mrdem-hs", "MRDEM hillshade (all of Canada, streamed)", ELEVATION, CANADA,
           "Pre-rendered hillshade of the MRDEM terrain model.",
           [Resource("MRDEM hillshade", Kind.COG, DEM_COG + "mrdem-30-dtm-hillshade.tif", "COG",
                     extra={"style": "hillshade"})],
           license="Open Government Licence - Canada", tags=["hillshade"]),
    _dem("hrdem-1m", "HRDEM 1 m lidar DTM (clip to extent)", "hrdem-mosaic-1m", CANADA,
         "NRCan High Resolution DEM mosaic from airborne lidar, where available.",
         "Open Government Licence - Canada"),
    _dem("3dep-10m", "USGS 3DEP 10 m DEM (clip to extent)", "3dep-seamless-10m", CONUS_AK_HI,
         "USGS 1/3 arc-second seamless DEM.", "Public domain"),
    _dem("cop30", "Copernicus GLO-30 DEM (clip to extent)", "cop-dem-glo-30", GLOBAL,
         "Global 30 m surface model.", "Copernicus DEM licence"),
    _entry("3dep-hs", "USGS 3DEP multidirectional hillshade", ELEVATION, CONUS_AK_HI,
           "Dynamic hillshade from the USGS elevation service.",
           [Resource("3DEP hillshade", Kind.WMS,
                     "https://elevation.nationalmap.gov/arcgis/services/3DEPElevation/ImageServer/WMSServer",
                     "WMS", "3DEPElevation:Hillshade Multidirectional")],
           license="Public domain"),
    _xyz("esri-hillshade", "Esri World Hillshade", ELEVATION,
         "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}",
         "Global multi-scale hillshade tiles.", zmax=16, attribution="Esri"),
    _bc("bc-contours", "TRIM contour lines (BC, 1:20k)", ELEVATION, "WHSE_BASEMAPPING.TRIM_CONTOUR_LINES",
        "20 m contours from the provincial TRIM base mapping.", tags=["contours"]),

    # ---------------------------------------------------------------- basemaps
    _xyz("osm", "OpenStreetMap", BASEMAPS, "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
         "Standard OSM map. Respect the tile usage policy for heavy use.", attribution="© OpenStreetMap contributors"),
    _xyz("esri-topo", "Esri World Topographic", BASEMAPS,
         "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
         "General-purpose topographic basemap.", attribution="Esri"),
    _xyz("opentopomap", "OpenTopoMap", BASEMAPS, "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
         "Topographic style rendered from OSM and SRTM.", zmax=17, attribution="© OpenTopoMap (CC-BY-SA)"),
    _xyz("carto-light", "Carto Positron (light)", BASEMAPS,
         "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
         "Muted light basemap that keeps your data in front.", attribution="© CARTO © OpenStreetMap contributors"),
    _xyz("carto-dark", "Carto Dark Matter", BASEMAPS,
         "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
         "Dark basemap.", attribution="© CARTO © OpenStreetMap contributors"),
    _xyz("bc-basemap", "BC Basemap (roads)", BASEMAPS,
         "https://maps.gov.bc.ca/arcgis/rest/services/province/roads_wm/MapServer/tile/{z}/{y}/{x}",
         "Province of BC roads basemap.", coverage=BC, attribution="Province of British Columbia"),
    _xyz("bc-topo", "BC Topographic (web mercator cache)", BASEMAPS,
         "https://maps.gov.bc.ca/arcgis/rest/services/province/web_mercator_cache/MapServer/tile/{z}/{y}/{x}",
         "Province of BC topographic basemap.", coverage=BC, attribution="Province of British Columbia"),
    _xyz("usgs-topo", "USGS Topo", BASEMAPS,
         "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
         "The National Map topographic basemap.", coverage=CONUS_AK_HI, zmax=16, attribution="USGS"),

    # ---------------------------------------------------------------- imagery
    _xyz("esri-imagery", "Esri World Imagery", IMAGERY,
         "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
         "High-resolution satellite and aerial imagery.", attribution="Esri, Maxar, Earthstar Geographics"),
    _xyz("s2cloudless", "Sentinel-2 cloudless 2020 (EOX)", IMAGERY,
         "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg",
         "Cloud-free 10 m Sentinel-2 mosaic. Non-commercial licence (CC BY-NC-SA 4.0).", zmax=15,
         license="CC BY-NC-SA 4.0", attribution="Sentinel-2 cloudless by EOX (Contains modified Copernicus data)"),
    _entry("s2-l2a", "Sentinel-2 scenes in view (pick date & cloud cover)", IMAGERY, GLOBAL,
           "Search recent Sentinel-2 L2A scenes over the map and add true colour or individual bands.",
           [Resource("Sentinel-2 L2A", Kind.STAC_COLLECTION, "https://earth-search.aws.element84.com/v1", "STAC",
                     "sentinel-2-l2a", extra={"provider": "earth_search", "preset": "sentinel2"})],
           license="Copernicus open licence"),

    # ---------------------------------------------------------------- water
    _bc("bc-streams", "Freshwater Atlas streams", HYDRO, "WHSE_BASEMAPPING.FWA_STREAM_NETWORKS_SP",
        "Every mapped stream in BC with stream order and watershed codes.", tags=["rivers", "hydrology"]),
    _bc("bc-lakes", "Freshwater Atlas lakes", HYDRO, "WHSE_BASEMAPPING.FWA_LAKES_POLY", "Lake polygons."),
    _bc("bc-rivers", "Freshwater Atlas rivers (polygons)", HYDRO, "WHSE_BASEMAPPING.FWA_RIVERS_POLY",
        "Double-line river polygons."),
    _bc("bc-wetlands", "Freshwater Atlas wetlands", HYDRO, "WHSE_BASEMAPPING.FWA_WETLANDS_POLY", "Wetland polygons."),
    _bc("bc-watersheds", "Assessment watersheds", HYDRO, "WHSE_BASEMAPPING.FWA_ASSESSMENT_WATERSHEDS_POLY",
        "Watershed units of roughly 2,000–10,000 ha used for cumulative-effects assessment."),

    # ---------------------------------------------------------------- transport
    _bc("bc-roads", "Digital Road Atlas", TRANSPORT, "WHSE_BASEMAPPING.DRA_DGTL_ROAD_ATLAS_MPAR_SP",
        "Authoritative road network for BC.", tags=["roads"]),
    _bc("bc-forest-roads", "Forest tenure road sections", TRANSPORT, "WHSE_FOREST_TENURE.FTEN_ROAD_SECTION_LINES_SVW",
        "Forest service and road-permit roads."),

    # ---------------------------------------------------------------- admin
    _bc("bc-municipalities", "Municipalities", ADMIN, "WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_MUNICIPALITIES_SP",
        "Legal municipal boundaries."),
    _bc("bc-regional-districts", "Regional districts", ADMIN, "WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_REGIONAL_DISTRICTS_SP",
        "Regional district boundaries."),
    _bc("bc-reserves", "Indian Reserves & Band Names", ADMIN, "WHSE_ADMIN_BOUNDARIES.CLAB_INDIAN_RESERVES",
        "Federal Indian Reserve boundaries (CLSS)."),
    _bc("bc-parks", "Parks, ecological reserves & protected areas", ADMIN, "WHSE_TANTALIS.TA_PARK_ECORES_PA_SVW",
        "Provincial parks, protected areas and ecological reserves.", tags=["parks"]),
    _bc("bc-tfl", "Tree Farm Licences", ADMIN, "WHSE_ADMIN_BOUNDARIES.FADM_TFL_ALL_SP", "TFL boundaries."),

    # ---------------------------------------------------------------- land
    _bc("bc-parcels", "ParcelMap BC parcel fabric", LAND, "WHSE_CADASTRE.PMBC_PARCEL_FABRIC_POLY_SVW",
        "Titled and Crown land parcels. Zoom in: this layer is dense.", tags=["cadastre", "property"]),

    # ---------------------------------------------------------------- ecology
    _bc("bc-vri", "Vegetation Resources Inventory (forest cover)", ECOLOGY,
        "WHSE_FOREST_VEGETATION.VEG_COMP_LYR_R1_POLY",
        "Forest cover polygons with species, age and height. Very dense: zoom in first.", tags=["forest", "vri"]),
    _bc("bc-bec", "Biogeoclimatic zones (BEC)", ECOLOGY, "WHSE_FOREST_VEGETATION.BEC_BIOGEOCLIMATIC_POLY",
        "Biogeoclimatic ecosystem classification zones, subzones and variants."),

    # ---------------------------------------------------------------- hazards
    _bc("bc-fire-current", "Current wildfire perimeters", HAZARDS,
        "WHSE_LAND_AND_NATURAL_RESOURCE.PROT_CURRENT_FIRE_POLYS_SP", "This season's fire perimeters (BCWS).",
        tags=["wildfire"]),
    _bc("bc-fire-historic", "Historical wildfire perimeters", HAZARDS,
        "WHSE_LAND_AND_NATURAL_RESOURCE.PROT_HISTORICAL_FIRE_POLYS_SP", "Fire perimeters back to 1917.",
        tags=["wildfire"]),

    # ---------------------------------------------------------------- geology
    _bc("bc-geology", "Bedrock geology", GEOLOGY, "WHSE_MINERAL_TENURE.GEOL_BEDROCK_UNIT_POLY_SVW",
        "BC Geological Survey digital bedrock geology."),
    _bc("bc-tenures", "Mineral, placer & coal tenures", GEOLOGY, "WHSE_MINERAL_TENURE.MTA_ACQUIRED_TENURE_SVW",
        "Active mineral titles."),

    # ---------------------------------------------------------------- places
    _bc("bc-names", "BC Geographical Names", PLACES, "WHSE_BASEMAPPING.GNS_GEOGRAPHICAL_NAMES_SP",
        "Official place names (lakes, peaks, communities...)."),
]


class CuratedProvider(Provider):
    id = "curated"
    label = "Quick picks"
    family = "curated"
    description = "Hand-picked, verified layers: DEMs, basemaps, imagery and the most-used BC layers."
    coverage = "BC / Canada / USA / Global"
    supports_bbox = True

    def __init__(self, entries=None):
        super().__init__(http=lambda *a, **k: {})
        self.entries = entries if entries is not None else ENTRIES

    def search(self, query: SearchQuery) -> SearchPage:
        words = [w.lower() for w in (query.text or "").split() if w]
        out = []
        for d in self.entries:
            hay = " ".join([d.title, d.description, d.category, " ".join(d.tags)]).lower()
            if words and not all(w in hay for w in words):
                continue
            if query.bbox and not bbox_intersects(d.bbox, query.bbox):
                continue
            if query.formats and not set(query.formats) & set(d.kinds):
                continue
            out.append(d)
        if query.sort == "title":
            out.sort(key=lambda d: d.title.lower())
        page = out[query.offset:query.offset + query.limit]
        return SearchPage(datasets=page, total=len(out), offset=query.offset)
