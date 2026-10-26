# SPDX-License-Identifier: GPL-2.0-or-later
from ..models import SearchQuery, SearchPage
from .. import net


class Provider:
    """A searchable source of datasets."""

    id = "base"
    label = "Base"
    family = ""            # ckan | stac | curated
    description = ""
    homepage = ""
    coverage = ""          # human readable: "British Columbia", "Canada", "Global"
    supports_bbox = False  # server-side spatial filtering
    supports_org = False

    def __init__(self, http=None):
        # ``http`` is injectable for tests: callable(url, params=None, data=None) -> parsed JSON
        self.http = http or net.fetch_json

    def search(self, query: SearchQuery) -> SearchPage:  # pragma: no cover - abstract
        raise NotImplementedError

    def __repr__(self):
        return f"<{type(self).__name__} {self.id}>"
