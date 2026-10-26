# SPDX-License-Identifier: GPL-2.0-or-later
"""Unit tests for the QGIS-independent core. Run: python -m unittest discover tests"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datum.core.models import Dataset, Resource, Kind, SearchQuery, bbox_intersects  # noqa: E402
from datum.core import sniff, dem  # noqa: E402
from datum.core.providers.ckan import BCDataCatalogue, OpenCanada, bbox_from_geojson  # noqa: E402
from datum.core.providers.stac import StacProvider, PlanetaryComputerSigner  # noqa: E402
from datum.core.catalog import ENTRIES, CuratedProvider  # noqa: E402

WMS_CAPS = b"""<?xml version="1.0"?>
<WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0">
 <Capability><Layer><Title>Root</Title><CRS>EPSG:4326</CRS><CRS>EPSG:3857</CRS>
  <Layer><Name>pub:LAKES</Name><Title>Lakes</Title><Abstract>Lake polys</Abstract>
   <EX_GeographicBoundingBox><westBoundLongitude>-139</westBoundLongitude><southBoundLatitude>48</southBoundLatitude>
   <eastBoundLongitude>-114</eastBoundLongitude><northBoundLatitude>60</northBoundLatitude></EX_GeographicBoundingBox>
   <CRS>EPSG:3005</CRS><Style><Name>default</Name></Style></Layer>
  <Layer><Title>Group only</Title><Layer><Name>roads</Name><Title>Roads</Title></Layer></Layer>
 </Layer></Capability></WMS_Capabilities>"""

WFS_CAPS = b"""<?xml version="1.0"?>
<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:ows="http://www.opengis.net/ows/1.1">
 <FeatureTypeList xmlns="http://www.opengis.net/wfs/2.0"><FeatureType><Name>pub:STREAMS</Name><Title>Streams</Title>
  <DefaultCRS>urn:ogc:def:crs:EPSG::3005</DefaultCRS>
  <ows:WGS84BoundingBox><ows:LowerCorner>-139 48</ows:LowerCorner><ows:UpperCorner>-114 60</ows:UpperCorner></ows:WGS84BoundingBox>
 </FeatureType></FeatureTypeList></wfs:WFS_Capabilities>"""


class FakeHttp:
    """Records calls and replays canned JSON keyed by URL suffix."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, params=None, data=None, **kw):
        self.calls.append((url, params, data))
        for suffix, payload in self.routes.items():
            if url.endswith(suffix):
                return payload(url, params, data) if callable(payload) else payload
        raise AssertionError(f"unexpected URL {url}")


class SniffTests(unittest.TestCase):
    def test_guess_kind(self):
        g = sniff.guess_kind
        self.assertEqual(g("https://x/{z}/{x}/{y}.png"), Kind.XYZ)
        self.assertEqual(g("https://x/ows?service=WMS&request=GetCapabilities"), Kind.WMS)
        self.assertEqual(g("https://x/geoserver/wfs"), Kind.WFS)
        self.assertEqual(g("https://x/arcgis/rest/services/A/B/FeatureServer/3"), Kind.ARCGIS_FEATURE)
        self.assertEqual(g("https://x/arcgis/rest/services/A/MapServer"), Kind.ARCGIS_MAP)
        self.assertEqual(g("https://x/arcgis/rest/services/A/ImageServer"), Kind.ARCGIS_IMAGE)
        self.assertEqual(g("https://x/dem.tif"), Kind.COG)
        self.assertEqual(g("https://x/data.geojson"), Kind.VECTOR_FILE)
        self.assertEqual(g("https://x/data.zip", "SHP"), Kind.VECTOR_FILE)
        self.assertEqual(g("https://x/doc.pdf"), Kind.LINK)

    def test_directory_listing_is_link(self):
        # Open Canada lists FTP folders with a SHP/GeoTIFF format
        self.assertEqual(sniff.guess_kind("http://ftp.maps.canada.ca/pub/canvec/shp/", "SHP"), Kind.LINK)
        self.assertEqual(sniff.guess_kind("https://x/GeoTIFFLCC/", "GeoTIFF"), Kind.LINK)

    def test_paths(self):
        self.assertEqual(sniff.s3_to_https("s3://bucket/a/b.tif"), "https://bucket.s3.amazonaws.com/a/b.tif")
        self.assertEqual(sniff.gdal_path("https://x/a.tif"), "/vsicurl/https://x/a.tif")
        self.assertEqual(sniff.gdal_path("https://x/a.zip"), "/vsizip//vsicurl/https://x/a.zip")
        self.assertEqual(sniff.gdal_path("/tmp/a.tif"), "/tmp/a.tif")

    def test_resource_from_url_extracts_layer(self):
        r = sniff.resource_from_url("https://x/wms?service=WMS&layers=foo&request=GetMap")
        self.assertEqual((r.kind, r.layer, r.url), (Kind.WMS, "foo", "https://x/wms"))
        r = sniff.resource_from_url("https://x/arcgis/rest/services/A/FeatureServer/2/query?where=1")
        self.assertEqual((r.kind, r.layer, r.url), (Kind.ARCGIS_FEATURE, "2", "https://x/arcgis/rest/services/A/FeatureServer"))

    def test_capabilities(self):
        self.assertEqual(sniff.detect_capabilities(WMS_CAPS), "wms")
        self.assertEqual(sniff.detect_capabilities(WFS_CAPS), "wfs")
        self.assertIsNone(sniff.detect_capabilities(b"<html></html>"))
        layers = sniff.parse_wms_capabilities(WMS_CAPS)
        self.assertEqual([l["name"] for l in layers], ["pub:LAKES", "roads"])
        self.assertIn("EPSG:3857", layers[0]["crs"])  # inherited from the root layer
        self.assertEqual(layers[0]["bbox"], (-139.0, 48.0, -114.0, 60.0))
        ft = sniff.parse_wfs_capabilities(WFS_CAPS)
        self.assertEqual(ft[0]["name"], "pub:STREAMS")
        self.assertEqual(ft[0]["bbox"], (-139.0, 48.0, -114.0, 60.0))

    def test_parse_xml_refuses_attacks(self):
        import xml.etree.ElementTree as ET
        bomb = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
                b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]><WMS_Capabilities>&lol2;</WMS_Capabilities>')
        xxe = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
               b'<WMS_Capabilities>&xxe;</WMS_Capabilities>')
        for doc in (bomb, xxe, "<a/>".encode("utf-16")):
            with self.assertRaises(ET.ParseError):
                sniff.parse_xml(doc)
        self.assertIsNone(sniff.detect_capabilities(bomb))  # detection treats it as "not a service"

    def test_parse_xml_allows_wms111_doctype(self):
        doc = (b'<?xml version="1.0"?><!DOCTYPE WMT_MS_Capabilities SYSTEM '
               b'"http://schemas.opengis.net/wms/1.1.1/WMS_MS_Capabilities.dtd"><WMT_MS_Capabilities version="1.1.1">'
               b'<Capability><Layer><Title>t</Title><Layer><Name>roads</Name><Title>Roads</Title>'
               b'<LatLonBoundingBox minx="-1" miny="-2" maxx="3" maxy="4"/></Layer></Layer></Capability>'
               b'</WMT_MS_Capabilities>')
        self.assertEqual(sniff.detect_capabilities(doc), "wms")
        self.assertEqual(sniff.parse_wms_capabilities(doc)[0]["bbox"], (-1.0, -2.0, 3.0, 4.0))

    def test_fetch_only_allows_http(self):
        from datum.core import net
        for url in ("file:///etc/passwd", "ftp://example.org/x", "javascript:alert(1)"):
            with self.assertRaises(net.NetworkError):
                net.fetch(url, use_cache=False)

    def test_pick_crs(self):
        self.assertEqual(sniff.pick_crs(["EPSG:4326", "EPSG:3005"], "EPSG:3005"), "EPSG:3005")
        self.assertEqual(sniff.pick_crs(["EPSG:4326", "EPSG:3857"], "EPSG:32610"), "EPSG:3857")
        self.assertEqual(sniff.pick_crs(["CRS:84"], "EPSG:32610"), "EPSG:4326")


class CkanTests(unittest.TestCase):
    BC_PKG = {
        "id": "abc", "name": "freshwater-lakes", "title": "Lakes", "notes": "<p>Lake <b>polygons</b></p>",
        "organization": {"title": "GeoBC", "name": "geobc"}, "license_title": "OGL-BC",
        "metadata_modified": "2025-01-02T00:00:00", "tags": [{"name": "water"}],
        "resources": [
            {"format": "wms", "url": "https://openmaps.gov.bc.ca/geo/pub/X/ows?service=WMS",
             "object_name": "WHSE_BASEMAPPING.FWA_LAKES_POLY", "bcdc_type": "geographic"},
            {"format": "kml", "url": "https://openmaps.gov.bc.ca/kml/x.kml",
             "object_name": "WHSE_BASEMAPPING.FWA_LAKES_POLY"},
            {"format": "multiple", "url": "https://catalogue.data.gov.bc.ca/dataset/x/download",
             "object_name": "WHSE_BASEMAPPING.FWA_LAKES_POLY", "name": "Custom download"},
            {"format": "pdf", "url": "https://x/spec.pdf", "name": "Spec"},
        ],
    }

    def test_bc_resources(self):
        ds = BCDataCatalogue(http=lambda *a, **k: {}).parse_package(self.BC_PKG)
        kinds = [r.kind for r in ds.resources]
        self.assertEqual(kinds, [Kind.WFS, Kind.WMS, Kind.LINK, Kind.LINK])
        wfs = ds.resources[0]
        self.assertEqual((wfs.url, wfs.layer, wfs.crs),
                         ("https://openmaps.gov.bc.ca/geo/pub/wfs", "pub:WHSE_BASEMAPPING.FWA_LAKES_POLY", "EPSG:3005"))
        self.assertEqual(ds.description, "Lake polygons")
        self.assertEqual(ds.best_resource().kind, Kind.WFS)
        self.assertEqual(ds.page_url, "https://catalogue.data.gov.bc.ca/dataset/freshwater-lakes")

    def test_params(self):
        p = OpenCanada(http=lambda *a, **k: {})
        params = p.build_params(SearchQuery(text="dem", bbox=(-124, 49, -123, 50), formats=[Kind.WMS],
                                            organization="nrcan-rncan", offset=25, limit=10))
        self.assertEqual(params["start"], 25)
        self.assertEqual(params["rows"], 10)
        self.assertIn('organization:"nrcan-rncan"', params["fq"])
        self.assertIn('res_format:("WMS" OR "wms")', params["fq"])
        self.assertEqual(params["ext_bbox"], "-124.00000,49.00000,-123.00000,50.00000")
        # BC can't filter spatially server-side
        self.assertNotIn("ext_bbox", BCDataCatalogue(http=None).build_params(SearchQuery(bbox=(0, 0, 1, 1))))

    def test_open_canada_language_and_bilingual(self):
        pkg = {"id": "1", "name": "n", "title_translated": {"en": "Rivers", "fr": "Rivières"},
               "organization": {"title": "Natural Resources Canada | Ressources naturelles Canada"},
               "spatial": '{"type": "Polygon", "coordinates": [[[-142, 41], [-52, 41], [-52, 84], [-142, 41]]]}',
               "resources": [
                   {"format": "WMS", "url": "https://maps.geogratis.gc.ca/wms/hydro_en?layers=x", "language": ["en"]},
                   {"format": "WMS", "url": "https://maps.geogratis.gc.ca/wms/hydro_fr?layers=x", "language": ["fr"]},
               ]}
        ds = OpenCanada(http=None).parse_package(pkg)
        self.assertEqual(ds.title, "Rivers")
        self.assertEqual(ds.organization, "Natural Resources Canada")
        self.assertEqual(len(ds.resources), 1)
        self.assertEqual(ds.bbox, (-142, 41, -52, 84))
        fr = OpenCanada(http=None, lang="fr").parse_package(pkg)
        self.assertEqual((fr.title, fr.resources[0].url), ("Rivières", "https://maps.geogratis.gc.ca/wms/hydro_fr"))

    def test_search_and_facets(self):
        http = FakeHttp({"/package_search": {"result": {
            "count": 7, "results": [self.BC_PKG],
            "search_facets": {"organization": {"items": [{"name": "geobc", "display_name": "GeoBC", "count": 5}]}}}}})
        page = BCDataCatalogue(http=http).search(SearchQuery(text="lakes"))
        self.assertEqual(page.total, 7)
        self.assertTrue(page.has_more)
        self.assertEqual(page.facets["organization"], [("geobc", "GeoBC", 5)])

    def test_bbox_from_geojson(self):
        self.assertIsNone(bbox_from_geojson(None))
        self.assertEqual(bbox_from_geojson({"type": "Point", "coordinates": [1, 2]}), (1, 2, 1, 2))


class StacTests(unittest.TestCase):
    COLLECTIONS = {"collections": [
        {"id": "mrdem-30", "title": "MRDEM 30 m / MNEMR", "description": "Elevation model",
         "keywords": ["dem"], "extent": {"spatial": {"bbox": [[-141, 41, -52, 84]]},
                                          "temporal": {"interval": [["2024-01-01T00:00:00Z", None]]}}},
        {"id": "landcover", "title": "Land cover", "description": "Classes",
         "extent": {"spatial": {"bbox": [[-141, 41, -52, 84]]}}},
        {"id": "europe", "title": "Euro DEM", "description": "dem",
         "extent": {"spatial": {"bbox": [[-10, 35, 30, 70]]}}},
    ], "links": []}

    def provider(self, routes=None):
        r = {"/collections": self.COLLECTIONS}
        r.update(routes or {})
        return StacProvider("t", "Test", "https://stac.example/api", http=FakeHttp(r))

    def test_keyword_and_bbox(self):
        p = self.provider()
        page = p.search(SearchQuery(text="dem"))
        self.assertEqual({d.id for d in page.datasets}, {"mrdem-30", "europe"})
        page = p.search(SearchQuery(text="dem", bbox=(-124, 49, -123, 50)))
        self.assertEqual([d.id for d in page.datasets], ["mrdem-30"])
        ds = page.datasets[0]
        self.assertEqual(ds.title, "MRDEM 30 m")
        self.assertEqual(ds.resources[0].kind, Kind.STAC_COLLECTION)
        self.assertEqual(ds.updated, "2024-01-01 → present")

    def test_search_items_pagination(self):
        page1 = {"features": [{"id": "a"}], "links": [{"rel": "next", "href": "https://stac.example/api/search",
                                                      "method": "POST", "body": {"token": "2"}}]}
        page2 = {"features": [{"id": "b"}], "links": []}

        def search(url, params, data):
            return page2 if data.get("token") == "2" else page1

        p = self.provider({"/search": search})
        items = p.search_items("c", (0, 0, 1, 1), datetime="2025-01-01/2025-02-01", max_cloud=10, limit=10)
        self.assertEqual([i["id"] for i in items], ["a", "b"])
        first_body = p.http.calls[-2][2]
        self.assertEqual(first_body["query"], {"eo:cloud_cover": {"lte": 10}})
        self.assertEqual(first_body["datetime"], "2025-01-01/2025-02-01")

    def test_asset_href_and_signing(self):
        signer = PlanetaryComputerSigner(lambda url, **kw: {"token": "sig=1"})
        p = StacProvider("pc", "PC", "https://pc/api", http=None, signer=signer)
        item = {"collection": "nasadem", "assets": {
            "elevation": {"href": "https://x.blob.core.windows.net/a.tif", "type": "image/tiff; application=geotiff"},
            "thumb": {"href": "https://x/t.png", "type": "image/png", "roles": ["thumbnail"]},
            "s3": {"href": "s3://bucket/k.tif", "type": "image/tiff"}}}
        self.assertEqual(p.asset_href(item, "elevation"), "https://x.blob.core.windows.net/a.tif?sig=1")
        self.assertEqual(p.asset_href(item, "s3"), "https://bucket.s3.amazonaws.com/k.tif")
        self.assertEqual(sorted(StacProvider.raster_assets(item)), ["elevation", "s3"])


class DemTests(unittest.TestCase):
    def test_candidates(self):
        bc = (-123.2, 49.2, -123.0, 49.3)
        ids = [s.id for s in dem.candidate_sources(bc, "dtm")]
        self.assertEqual(ids[0], "hrdem-mosaic-1m")
        self.assertEqual(ids[-1], "cop-dem-glo-30")  # DSM-only source comes last for a DTM request
        europe = (10, 45, 11, 46)
        self.assertEqual([s.id for s in dem.candidate_sources(europe, "dtm")], ["cop-dem-glo-30"])

    def test_sizes(self):
        self.assertAlmostEqual(dem.estimate_mb(1, 1), 4.0)
        self.assertEqual(dem.fit_resolution(10, 1, 1000), 1)
        self.assertEqual(dem.fit_resolution(1000, 1, 500), 4.0)   # 1000 km2 at 4 m = 250 MB
        self.assertEqual(dem.fit_resolution(292000, 30, 500), 60.0)  # MRDEM over southern BC
        self.assertEqual(dem.overview_factor(292000, 30, 500), 2)
        self.assertGreater(dem.bbox_area_km2((-123.2, 49.2, -123.0, 49.3)), 100)

    def test_asset_fallback_and_filter(self):
        cop = dem.SOURCES_BY_ID["cop-dem-glo-30"]
        self.assertEqual(dem.asset_for(cop, "dtm"), ("data", "dsm"))
        tdep = dem.SOURCES_BY_ID["3dep-seamless-10m"]
        items = [{"properties": {"gsd": 10}}, {"properties": {"gsd": 30}}]
        self.assertEqual(dem.filter_items(items, tdep), items[:1])

    def test_find_tiles_newest_project(self):
        lidar = dem.SOURCES_BY_ID["hrdem-lidar"]

        class P:
            def search_items(self, *a, **k):
                return [{"properties": {"datetime": "2016"}, "assets": {"dtm": {"href": "old.tif"}}},
                        {"properties": {"datetime": "2019"}, "assets": {"dtm": {"href": "new.tif"}}}]

            def asset_href(self, it, key):
                return it["assets"][key]["href"]

        b = dem.DemBuilder({"nrcan_stac": P()})
        self.assertEqual(b.find_tiles(lidar, "dtm", (0, 0, 1, 1), "newest"), (["new.tif"], "dtm"))
        self.assertEqual(b.find_tiles(lidar, "dtm", (0, 0, 1, 1), "mosaic")[0], ["old.tif", "new.tif"])


try:
    from osgeo import osr  # noqa: F401
    HAVE_GDAL = True
except ImportError:
    HAVE_GDAL = False


@unittest.skipUnless(HAVE_GDAL, "needs GDAL (run with QGIS's Python)")
class ScaleTests(unittest.TestCase):
    def wkt(self, epsg):
        from osgeo import osr
        s = osr.SpatialReference()
        s.ImportFromEPSG(epsg)
        return s.ExportToWkt()

    def test_web_mercator_is_stretched(self):
        # 50°N: one real metre is 1/cos(50°) ≈ 1.556 mercator units
        y = 6446275.8  # 50°N in EPSG:3857
        upm = dem.units_per_metre(self.wkt(3857), (-13.7e6, y - 1000, -13.6e6, y + 1000))
        self.assertAlmostEqual(upm, 1 / math.cos(math.radians(50)), delta=0.01)

    def test_bc_albers_is_true_metres(self):
        upm = dem.units_per_metre(self.wkt(3005), (1.2e6, 4.8e5, 1.3e6, 5.8e5))
        self.assertAlmostEqual(upm, 1.0, delta=0.01)  # Albers distortion + spherical distance

    def test_geographic(self):
        self.assertAlmostEqual(dem.units_per_metre(self.wkt(4326), (-124, 49, -123, 50)), 1 / 110574.0)


class ModelAndCatalogTests(unittest.TestCase):
    def test_roundtrip_and_preference(self):
        ds = Dataset("1", "T", "bcdc", bbox=(1, 2, 3, 4), resources=[
            Resource("map", Kind.WMS, "u", layer="l"), Resource("feat", Kind.WFS, "u", layer="l")])
        self.assertEqual(ds.best_resource().kind, Kind.WFS)
        self.assertEqual(ds.best_resource([Kind.WMS]).kind, Kind.WMS)
        back = Dataset.from_dict(ds.to_dict())
        self.assertEqual((back.key, back.bbox, back.resources[1].layer), ("bcdc:1", (1, 2, 3, 4), "l"))

    def test_bbox_intersects(self):
        self.assertTrue(bbox_intersects(None, (0, 0, 1, 1)))
        self.assertTrue(bbox_intersects((0, 0, 2, 2), (1, 1, 3, 3)))
        self.assertFalse(bbox_intersects((0, 0, 1, 1), (2, 2, 3, 3)))

    def test_catalog_entries(self):
        ids = [e.id for e in ENTRIES]
        self.assertEqual(len(ids), len(set(ids)))
        for e in ENTRIES:
            self.assertTrue(e.resources and all(r.addable for r in e.resources), e.id)
            self.assertTrue(e.extra.get("coverage"), e.id)
            for r in e.resources:
                if r.kind == Kind.DEM:
                    self.assertTrue(r.layer == dem.AUTO or r.layer in dem.SOURCES_BY_ID, e.id)

    def test_curated_search(self):
        p = CuratedProvider()
        self.assertTrue(any(d.id == "bc-streams" for d in p.search(SearchQuery(text="streams")).datasets))
        europe = p.search(SearchQuery(bbox=(10, 45, 11, 46), limit=100)).datasets
        self.assertFalse(any(d.extra["coverage"] == "BC" for d in europe))
        tiles = p.search(SearchQuery(formats=[Kind.XYZ], limit=100)).datasets
        self.assertTrue(tiles and all(Kind.XYZ in d.kinds for d in tiles))


if __name__ == "__main__":
    unittest.main()
