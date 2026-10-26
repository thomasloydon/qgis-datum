# SPDX-License-Identifier: GPL-2.0-or-later
"""Provider registry: built-in portals plus any custom CKAN / STAC endpoints from settings."""

from .base import Provider
from .ckan import CkanProvider, BCDataCatalogue, OpenCanada
from .stac import StacProvider, nrcan_datacube, earth_search, planetary_computer


# Portals that can be switched on from Settings with one click.
KNOWN_PORTALS = [
    {"name": "Alberta Open Data", "url": "https://open.alberta.ca", "type": "ckan"},
    {"name": "Ontario Data Catalogue", "url": "https://data.ontario.ca", "type": "ckan"},
    {"name": "Humanitarian Data Exchange", "url": "https://data.humdata.org", "type": "ckan"},
]


def custom_id(name):
    return "custom_" + "".join(ch if ch.isalnum() else "_" for ch in name.lower())


def build_registry(custom_endpoints=(), lang="en", http=None):
    """Return an ordered dict-like list of providers keyed by id."""
    from ..catalog import CuratedProvider
    providers = [
        CuratedProvider(),
        BCDataCatalogue(http=http),
        OpenCanada(http=http, lang=lang),
        nrcan_datacube(http=http),
        earth_search(http=http),
        planetary_computer(http=http),
    ]
    for ep in custom_endpoints:
        pid = custom_id(ep["name"])
        if ep.get("type") == "stac":
            providers.append(StacProvider(pid, ep["name"], ep["url"], http=http,
                                          description="Custom STAC API", coverage="Custom"))
        else:
            providers.append(CkanProvider(pid, ep["name"], ep["url"], http=http,
                                          supports_bbox=bool(ep.get("bbox")),
                                          description="Custom CKAN portal", coverage="Custom"))
    return {p.id: p for p in providers}
