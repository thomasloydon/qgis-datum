# Development

## Setup

```sh
git clone https://github.com/thomasloydon/qgis-datum.git
cd qgis-datum
make deploy      # symlink datum/ into your QGIS profile (macOS path by default)
```

On Linux or Windows, point `QGIS_PLUGINS` at your profile's plugin folder:

```sh
make deploy QGIS_PLUGINS="$HOME/.local/share/QGIS/QGIS3/profiles/default/python/plugins"
```

Restart QGIS and enable **Datum** in *Plugins › Manage and Install Plugins*. After editing code, restart QGIS or use the [Plugin Reloader](https://plugins.qgis.org/plugins/plugin_reloader/) plugin.

Datum only needs what ships with QGIS: Python 3.9 or newer, PyQt5 or PyQt6, and GDAL. The development tools are optional: `pip install ruff`.

## Layout

```
datum/
  __init__.py, plugin.py   QGIS entry point: toolbar action, menu, Ctrl+Alt+D, dock lifecycle
  metadata.txt             plugin metadata (version, changelog, links)
  core/                    logic; no Qt widgets
    models.py              Dataset, Resource, Kind, SearchQuery/SearchPage   (pure Python)
    sniff.py               URL classification, GDAL paths, WMS/WFS/WMTS capability parsing (pure)
    providers/             Provider base, CKAN (BC, Open Canada, custom), STAC (+ PC signing) (pure)
    catalog.py             Quick-add entries + CuratedProvider                (pure)
    dem.py                 DEM sources, planning helpers, DemBuilder (GDAL; no QGIS)
    net.py                 HTTP: QgsBlockingNetworkRequest inside QGIS, urllib outside; small TTL cache
    loader.py              Resource -> QgsMapLayer, styling, project insertion, vector downloads
    tasks.py               QgsTask wrapper; results delivered on the main thread
    settings.py, store.py  QgsSettings access; favourites/history JSON in the profile
  ui/
    dock.py                header, tabs, footer; owns the provider registry and DataActions
    actions.py             DataActions: the one place that routes "add this" for every tab
    search_tab.py, quick_tab.py, dem_tab.py, url_tab.py, library_tab.py, settings_tab.py
    dialogs.py             layer picker, STAC imagery browser
    widgets.py             result model and card delegate, area-of-interest picker
    theme.py               palette-aware stylesheet and tintable SVG line icons
tests/
  test_core.py             unit tests for the pure core (GDAL-dependent tests skip without GDAL)
  qgis_smoke.py            offline end-to-end checks inside headless QGIS
  qgis_integration.py      live-service checks inside headless QGIS
scripts/release.py         metadata check, zip build, plugins.qgis.org upload
```

### Design notes

- **Pure core.** Providers, URL sniffing, models and DEM planning don't import QGIS, so they're unit-tested with stock Python. Providers take an injectable `http` callable, and tests pass a fake one.
- **Nothing blocks the UI.** Every network or GDAL call runs in a `QgsTask` via `core.tasks.run(description, fn, done)`. `done(ok, result, error)` is called on the main thread, and only there are layers created and added to the project.
- **QGIS networking.** `core.net` uses `QgsBlockingNetworkRequest`, so proxies, SSL settings and QGIS authentication apply. Responses are cached for 10 minutes.
- **Everything goes through `DataActions.add`.** It decides between live layer, download, layer picker, STAC browser and DEM builder, so all tabs behave the same.
- **Qt5/Qt6.** Enums are written fully qualified (`Qt.AlignmentFlag.AlignLeft`) and `QAction` is imported with a fallback, so the plugin runs under both bindings. `metadata.txt` declares `supportsQt6=True`.

## Tests

| Command | What it runs | Needs |
|---|---|---|
| `make lint` | ruff | `pip install ruff` |
| `make scan` | Bandit, flake8 and detect-secrets, the scanners plugins.qgis.org runs on uploads | `pip install bandit flake8 detect-secrets` |
| `make test` | `tests/test_core.py` (GDAL tests skipped) | Python 3.9+ |
| `make test-smoke` | `tests/qgis_smoke.py` in headless QGIS (plugin, dock, styling, terrain products) | QGIS installed (macOS paths by default) |
| `make test-qgis` | `tests/qgis_integration.py` against the live services | QGIS + internet |

The QGIS tests run with `QT_QPA_PLATFORM=offscreen` and a mocked `iface`. They redirect `QGIS_CUSTOM_CONFIG_PATH` and `QSettings` to a temporary folder so they never touch your real profile. On macOS, QGIS still writes one native preference file before any redirect applies, and the Makefile removes it afterwards if it didn't exist before.

To use a QGIS other than `/Applications/QGIS.app`, set `QGIS_APP`, or run the scripts with that QGIS's Python:

```sh
QT_QPA_PLATFORM=offscreen python3 tests/qgis_smoke.py
```

CI runs all of this in the official `qgis/qgis` containers; see [releasing.md](releasing.md).

## Adding a data source

**A CKAN portal or STAC API:** users can already add these in Settings. To ship one built in, add it to `KNOWN_PORTALS` in `core/providers/__init__.py` (one-click in Settings), or construct it in `build_registry` and add a colour in `ui/theme.SOURCE_COLORS`.

**A portal with its own conventions:** subclass `CkanProvider` and override `parse_resources`, as `BCDataCatalogue` does to turn warehouse objects into WFS/WMS. For a non-CKAN, non-STAC API, subclass `Provider` and implement `search(query) -> SearchPage`.

**A quick-add layer:** add an entry to `ENTRIES` in `core/catalog.py` using the helpers `_bc()` (BC WFS+WMS), `_xyz()` (tiles), `_dem()` (elevation builder) or `_entry()` (anything). Verify the URL works first. The catalogue test checks that ids are unique and every entry is addable.

**A DEM source:** add a `DemSource` to `DEM_SOURCES` in `core/dem.py` with its STAC provider, collection, asset keys per surface, native resolution and coverage. Add it to `AUTO_ORDER` if auto mode should consider it.

Then add unit tests with a fake `http`. See `CkanTests` and `StacTests` in `tests/test_core.py`.

## Style

- ruff config is in `pyproject.toml`. CI fails on lint errors.
- Match the surrounding code: short docstrings that explain why, few comments.
- Keep `core/` free of widgets. Keep the pure modules free of QGIS imports.
- User-facing text uses sentence case and plain words.
