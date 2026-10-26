# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.1] - 2026-10-25

### Fixed
- The plugin package now includes `LICENSE`, which plugins.qgis.org requires.

## [1.0.0] - 2026-10-25

First public release.

### Added
- **Search** across the BC Data Catalogue, Open Government Canada, the NRCan GEO.ca datacube, Earth Search and Microsoft Planetary Computer, with filters for format, organisation and map extent, sorting, paging, result cards and a details panel.
- **Quick add**: about 40 checked layers (elevation, basemaps, imagery, BC water, roads, boundaries, parcels, forests, wildfire, geology, place names).
- **Elevation builder**: auto best-available DEM (HRDEM 1 m → MRDEM 30 m → USGS 3DEP 10 m → Copernicus 30 m), 12 DEM sources, download or stream, CRS/resolution/resampling/compression options, a size budget, and hillshade, slope, aspect, roughness, TRI, TPI and contours.
- **STAC imagery browser** with area, date and cloud filters, asset choice, mosaicking and clipped download; Planetary Computer assets are signed automatically.
- **Add by URL** with detection of WMS/WMTS/WFS, ArcGIS REST, XYZ, COG and vector files, and of CKAN/STAC catalogues as new search sources.
- **Library** of favourites (with import and export) and history.
- Settings for sources, layer grouping, metadata, vector defaults, downloads, imagery defaults and language.
- CI (lint, unit tests, headless QGIS LTR/stable/nightly, CodeQL) and tag-driven releases to GitHub and plugins.qgis.org (per-plugin upload token or OSGeo ID).

### Fixed during pre-release testing
- DEM size budget was wrong in Web Mercator and other non-metric-scale projections, giving outputs up to 2.4× too large.
- Large downloads now read source overviews instead of full-resolution data (3–4× faster).
- One-click DEMs over large areas stream instead of downloading.
- Contours and 8-bit hillshade output failed with some GDAL options.
- Hillshades streaked when QGIS drew from coarse overviews; DEM layers now use bilinear resampling.
- BC WMS default projection is now chosen by exact host match rather than a URL prefix (flagged by CodeQL).

[Unreleased]: https://github.com/thomasloydon/qgis-datum/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/thomasloydon/qgis-datum/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/thomasloydon/qgis-datum/releases/tag/v1.0.0
