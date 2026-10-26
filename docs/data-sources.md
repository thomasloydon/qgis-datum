# Data sources

Datum doesn't host data. It finds and loads data from public services. This page lists what each source provides, how Datum talks to it, and what the licence asks of you. **Licences belong to the data providers.** Datum copies each dataset's licence and publisher into the layer metadata, but checking the terms for your use is up to you.

## Searchable catalogues

### BC Data Catalogue
- **Portal:** https://catalogue.data.gov.bc.ca (CKAN API `/api/3/action/package_search`)
- **Services:** BC Geographic Warehouse layers through the provincial GeoServer.
  - WFS `https://openmaps.gov.bc.ca/geo/pub/wfs`, layers named `pub:<SCHEMA.OBJECT>`, requested in **EPSG:3005** (BC Albers)
  - WMS `https://openmaps.gov.bc.ca/geo/pub/wms`
- **Licence:** mostly the [Open Government Licence – British Columbia](https://www2.gov.bc.ca/gov/content/data/open-data/open-government-licence-bc). Some records have other or restricted licences, which are shown on each result.
- **Notes:** BC records don't carry a spatial extent, so **In view** can't narrow them. Datum turns each warehouse object into canonical WFS and WMS resources and lists the catalogue's own download links separately.

### Open Government Canada
- **Portal:** https://open.canada.ca/data (CKAN, with server-side extent filtering via `ext_bbox`)
- **Services:** whatever each record publishes: WMS, ArcGIS REST, GeoJSON, KML, zipped shapefiles and so on. Records are bilingual, and Datum keeps the resources in your chosen language (Settings › Search).
- **Licence:** mostly the [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada).

### NRCan GEO.ca Datacube (STAC)
- **API:** https://datacube.services.geo.ca/stac/api
- **Highlights:** `mrdem-30`, `hrdem-mosaic-1m`, `hrdem-mosaic-2m`, `hrdem-lidar`, `cdem`, `cdsm`, `landcover`, surface-water and air-photo series, all as cloud-optimised GeoTIFFs. Elevation files are served from `canelevation-dem.s3.ca-central-1.amazonaws.com`.
- **Licence:** Open Government Licence – Canada.

### Earth Search (Element 84, AWS Open Data)
- **API:** https://earth-search.aws.element84.com/v1
- **Highlights:** `sentinel-2-l2a`, `sentinel-1-grd`, `cop-dem-glo-30`, `cop-dem-glo-90`, `naip`. Landsat is hidden because its bucket is requester-pays.
- **Licence:** Sentinel data is under the [Copernicus open data terms](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice). The Copernicus DEM has its [own licence](https://registry.opendata.aws/copernicus-dem/), which is free and requires attribution.

### Microsoft Planetary Computer
- **API:** https://planetarycomputer.microsoft.com/api/stac/v1
- **Highlights:** `3dep-seamless`, `3dep-lidar-dtm`, `3dep-lidar-dsm`, `nasadem`, `alos-dem`, Landsat, Sentinel, ESA WorldCover and about 130 other collections.
- **Signing:** asset URLs need a short-lived SAS token. Datum gets one from `/api/sas/v1/token/<collection>` and caches it for about 45 minutes. Streamed layers stop working after roughly an hour, so download anything you need to keep.
- **Licence:** varies by collection, and is shown on each result (USGS products are public domain).

### Custom catalogues
Any **CKAN** portal (it must answer `/api/3/action/package_search`) or **STAC API** (it must answer `/collections` and `/search`) can be added in Settings or from the URL tab. Alberta Open Data, the Ontario Data Catalogue and the Humanitarian Data Exchange are preset.

## Quick-add layers

| Layer | Service | Licence / attribution |
|---|---|---|
| MRDEM 30 m DTM / DSM / hillshade | COG on `canelevation-dem` | OGL – Canada |
| HRDEM, 3DEP, Copernicus (clip to extent) | Elevation builder (STAC) | as for the source above |
| USGS 3DEP multidirectional hillshade | WMS `elevation.nationalmap.gov` | Public domain (USGS) |
| Esri World Hillshade / Topographic / Imagery | Esri tile services | © Esri and its data providers; see the [Esri terms of use](https://www.esri.com/en-us/legal/terms/full-master-agreement) |
| OpenStreetMap | `tile.openstreetmap.org` | © OpenStreetMap contributors (ODbL). Follow the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/): no bulk downloading. |
| OpenTopoMap | `tile.opentopomap.org` | © OpenTopoMap (CC-BY-SA), © OpenStreetMap contributors |
| Carto Positron / Dark Matter | `basemaps.cartocdn.com` | © CARTO, © OpenStreetMap contributors |
| BC Basemap, BC Topographic | `maps.gov.bc.ca` ArcGIS tiles | Province of British Columbia |
| USGS Topo | `basemap.nationalmap.gov` | Public domain (USGS) |
| Sentinel-2 cloudless 2020 | EOX tiles | **CC BY-NC-SA 4.0, non-commercial only.** "Sentinel-2 cloudless by EOX IT Services GmbH (contains modified Copernicus Sentinel data 2020)" |
| Sentinel-2 scenes in view | Earth Search STAC | Copernicus open data terms |
| BC water, roads, boundaries, parcels, forests, fire, geology, names | BC WFS/WMS | OGL – British Columbia, unless the dataset says otherwise |

## Adding a source to Datum

Is there a catalogue or layer you'd like built in? [Open a data-source request](https://github.com/thomasloydon/qgis-datum/issues/new?template=data_source.yml) or see [development.md](development.md#adding-a-data-source).
