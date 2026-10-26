# SPDX-License-Identifier: GPL-2.0-or-later
"""End-to-end check inside headless QGIS. Hits the real services, so it's opt-in.

    make test-qgis

Settings, favourites and downloads go to a temporary sandbox, not your profile.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile  # noqa: E402

from qgis.PyQt.QtCore import QSettings  # noqa: E402
from qgis.core import (  # noqa: E402
    QgsApplication, QgsProject, QgsCoordinateReferenceSystem, QgsRectangle, QgsVectorLayer,
)

# Keep settings, favourites and downloads out of the real profile. On macOS Qt
# ignores $HOME, so also redirect QSettings and the QGIS config folder explicitly.
SANDBOX = tempfile.mkdtemp(prefix="datum-test-")
os.environ["HOME"] = SANDBOX
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = SANDBOX
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, SANDBOX)
app = QgsApplication([], True)
app.initQgis()

from qgis.testing.mocked import get_iface  # noqa: E402
import qgis.utils  # noqa: E402

iface = get_iface()
qgis.utils.iface = iface
canvas = iface.mapCanvas()
canvas.resize(800, 600)
crs = QgsCoordinateReferenceSystem("EPSG:3005")
QgsProject.instance().setCrs(crs)
canvas.setDestinationCrs(crs)
canvas.setExtent(QgsRectangle(1210000, 480000, 1214000, 483000))  # North Vancouver

from datum.ui.dock import DatumDock  # noqa: E402
from datum.core.catalog import ENTRIES  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        failures.append(name)


def pump(cond, timeout=240):
    t = time.time()
    while not cond() and time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.05)
    return cond()


dock = DatumDock(iface)
actions = dock.actions

# search every source
st = dock.search_tab
st.box.setText("lakes")
st.search()
pump(lambda: st.pending == 0, 90)
check("search all sources", st.model.rowCount() > 10 and not st.errors, f"{st.model.rowCount()} rows, errors={st.errors}")

# quick picks of every kind
for eid in ("osm", "mrdem-hs", "bc-streams", "3dep-hs"):
    actions.add(next(e for e in ENTRIES if e.id == eid))
names = {l.name(): l.isValid() for l in QgsProject.instance().mapLayers().values()}
check("quick picks added", len(names) == 4 and all(names.values()), str(names))

# DEM with derivatives
done = {}
dt = dock.dem_tab
dt.select_source("mrdem-30")
for cb in (dt.hillshade, dt.slope, dt.contours):
    cb.setChecked(True)
actions.run_dem(dt.build_request(), on_done=lambda *a: done.update(dem=a))
pump(lambda: "dem" in done)
ok, result, err = done["dem"]
check("dem build", ok and result and set(result.outputs) == {"hillshade", "slope", "contours"}, str(err or ""))
if ok:
    check("contours non-empty", QgsVectorLayer(result.outputs["contours"]).featureCount() > 0)

# WFS download
before = len(QgsProject.instance().mapLayers())
lakes = next(e for e in ENTRIES if e.id == "bc-streams")
actions.download_vector(lakes, lakes.resources[0])
pump(lambda: not actions._busy)
check("wfs download", len(QgsProject.instance().mapLayers()) == before + 1)

QgsProject.instance().clear()
import shutil  # noqa: E402
shutil.rmtree(SANDBOX, ignore_errors=True)
print("\nFAILED: " + ", ".join(failures) if failures else "\nAll integration checks passed.")
# skip interpreter teardown: tearing down QGIS with a mocked iface can segfault after the results are in
sys.stdout.flush()
os._exit(1 if failures else 0)
