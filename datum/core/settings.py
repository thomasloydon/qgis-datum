# SPDX-License-Identifier: GPL-2.0-or-later
"""Typed access to the plugin's QgsSettings."""

import json
import os

from qgis.core import QgsSettings, QgsApplication

PREFIX = "datum/"

DEFAULTS = {
    "enabled_providers": ["curated", "bcdc", "opencanada", "nrcan_stac", "earth_search", "planetary"],
    "page_size": 25,
    "timeout": 30,
    "download_dir": "",
    "group_name": "Datum",
    "group_by_source": False,
    "zoom_to_layer": False,
    "bc_default": "wfs",            # wfs | wms | download
    "wfs_max_features": 0,          # 0 = unlimited
    "wfs_download_format": "GPKG",  # GPKG | GeoJSON | ESRI Shapefile
    "lang": "en",
    "custom_endpoints": [],         # [{"name", "url", "type": ckan|stac, "bbox": bool}]
    "filter_to_extent": False,
    "dem_max_mb": 500,
    "dem_style": "elevation",       # elevation | hillshade | grey
    "dem_blend_hillshade": True,
    "add_metadata": True,
    "stac_max_items": 20,
    "stac_max_cloud": 20,
    "stac_days": 60,
    "last_tab": 0,
}


def _decode(key, raw):
    default = DEFAULTS[key]
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw in (True, "true", "True", "1", 1)
    if isinstance(default, int):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    if isinstance(default, (list, dict)):
        if isinstance(raw, (list, dict)):
            return raw
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default
    return raw


def get(key):
    return _decode(key, QgsSettings().value(PREFIX + key, None))


def set(key, value):  # noqa: A001 - mirrors QgsSettings API
    if isinstance(DEFAULTS.get(key), (list, dict)):
        value = json.dumps(value)
    QgsSettings().setValue(PREFIX + key, value)


def reset():
    s = QgsSettings()
    for k in DEFAULTS:
        s.remove(PREFIX + k)


def data_dir():
    """Folder for favourites/history and default downloads."""
    path = os.path.join(QgsApplication.qgisSettingsDirPath(), "datum")
    os.makedirs(path, exist_ok=True)
    return path


def download_dir(create=False):
    path = get("download_dir") or os.path.join(os.path.expanduser("~"), "Datum downloads")
    if create:
        os.makedirs(path, exist_ok=True)
    return path
