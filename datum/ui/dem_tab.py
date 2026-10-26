# SPDX-License-Identifier: GPL-2.0-or-later
"""Elevation builder: pick a source and an area, get a clipped DEM plus terrain derivatives."""

import os

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QRadioButton, QButtonGroup, QGroupBox, QLabel,
    QCheckBox, QDoubleSpinBox, QSpinBox, QPushButton, QProgressBar, QScrollArea, QFrame, QLineEdit, QGridLayout,
)
from qgis.core import QgsProject, QgsCoordinateReferenceSystem
from qgis.gui import QgsProjectionSelectionWidget, QgsFileWidget

from ..core import settings
from ..core.dem import (
    DEM_SOURCES, SOURCES_BY_ID, AUTO, RESAMPLING, COMPRESSION, DemRequest, bbox_area_km2, estimate_mb,
    fit_resolution, candidate_sources, safe_name,
)
from ..core.models import bbox_intersects
from . import theme
from .widgets import AoiPicker, hint


class DemTab(QWidget):
    def __init__(self, iface, actions, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.actions = actions
        self.task = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # ------------------------------------------------ source
        g = QGroupBox("Elevation source")
        gl = QVBoxLayout(g)
        self.source = QComboBox()
        self.source.addItem(theme.accent_icon("zap"), "Best available for the area (auto)", AUTO)
        for s in DEM_SOURCES:
            self.source.addItem(theme.icon("mountain"), f"{s.title}  ·  {s.coverage_label}", s.id)
        gl.addWidget(self.source)
        srow = QHBoxLayout()
        self.dtm = QRadioButton("Bare earth (DTM)")
        self.dsm = QRadioButton("Surface (DSM)")
        self.dtm.setChecked(True)
        self.surface_group = QButtonGroup(self)
        self.surface_group.addButton(self.dtm)
        self.surface_group.addButton(self.dsm)
        srow.addWidget(self.dtm)
        srow.addWidget(self.dsm)
        srow.addStretch(1)
        gl.addLayout(srow)
        self.lidar_row = QHBoxLayout()
        self.lidar = QComboBox()
        self.lidar.addItem("Use the newest lidar project", "newest")
        self.lidar.addItem("Mosaic all projects (newest on top)", "mosaic")
        self.lidar_lbl = QLabel("Overlaps:")
        self.lidar_row.addWidget(self.lidar_lbl)
        self.lidar_row.addWidget(self.lidar, 1)
        gl.addLayout(self.lidar_row)
        self.source_info = hint("")
        gl.addWidget(self.source_info)
        lay.addWidget(g)

        # ------------------------------------------------ area
        g = QGroupBox("Area")
        gl = QVBoxLayout(g)
        self.aoi = AoiPicker(iface, self)
        gl.addWidget(self.aoi)
        lay.addWidget(g)

        # ------------------------------------------------ output
        g = QGroupBox("Output")
        form = QFormLayout(g)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        mrow = QHBoxLayout()
        self.download = QRadioButton("Download GeoTIFF")
        self.stream = QRadioButton("Stream (no download)")
        self.download.setChecked(True)
        self.download.setToolTip("Clip, mosaic and reproject into a local GeoTIFF. Needed for derivatives.")
        self.stream.setToolTip("Creates a tiny VRT that reads the remote tiles on demand. Instant, but needs internet.")
        mg = QButtonGroup(self)
        mg.addButton(self.download)
        mg.addButton(self.stream)
        mrow.addWidget(self.download)
        mrow.addWidget(self.stream)
        mrow.addStretch(1)
        form.addRow("Mode", mrow)

        rrow = QHBoxLayout()
        self.res_mode = QComboBox()
        self.res_mode.addItem("Native (auto-coarsen if too big)", "auto")
        self.res_mode.addItem("Custom", "custom")
        self.res = QDoubleSpinBox()
        self.res.setRange(0.5, 5000)
        self.res.setDecimals(1)
        self.res.setValue(10)
        self.res.setSuffix(" m")
        rrow.addWidget(self.res_mode, 1)
        rrow.addWidget(self.res)
        form.addRow("Resolution", rrow)

        self.crs = QgsProjectionSelectionWidget()
        self.crs.setOptionVisible(QgsProjectionSelectionWidget.CrsOption.ProjectCrs, True)
        pcrs = QgsProject.instance().crs()
        self.crs.setCrs(pcrs if pcrs.isValid() else QgsCoordinateReferenceSystem("EPSG:3005"))
        form.addRow("CRS", self.crs)

        self.resampling = QComboBox()
        self.resampling.addItems(RESAMPLING)
        form.addRow("Resampling", self.resampling)
        self.compression = QComboBox()
        self.compression.addItems(COMPRESSION)
        form.addRow("Compression", self.compression)

        self.folder = QgsFileWidget()
        self.folder.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self.folder.setFilePath(os.path.join(settings.download_dir(), "dem"))
        form.addRow("Folder", self.folder)
        self.name = QLineEdit()
        self.name.setPlaceholderText("automatic")
        form.addRow("File name", self.name)
        self.max_mb = QSpinBox()
        self.max_mb.setRange(10, 20000)
        self.max_mb.setSingleStep(100)
        self.max_mb.setSuffix(" MB")
        self.max_mb.setValue(settings.get("dem_max_mb"))
        self.max_mb.setToolTip("With native resolution, the DEM is resampled to stay under this size")
        form.addRow("Size budget", self.max_mb)
        lay.addWidget(g)

        # ------------------------------------------------ derivatives
        self.deriv_box = QGroupBox("Terrain products")
        grid = QGridLayout(self.deriv_box)
        self.hillshade = QCheckBox("Hillshade")
        self.hs_multi = QCheckBox("multidirectional")
        self.hs_multi.setChecked(True)
        self.zf = QDoubleSpinBox()
        self.zf.setRange(0.1, 20)
        self.zf.setValue(1.0)
        self.zf.setPrefix("z ×")
        self.slope = QCheckBox("Slope")
        self.slope_unit = QComboBox()
        self.slope_unit.addItems(["degrees", "percent"])
        self.aspect = QCheckBox("Aspect")
        self.rough = QCheckBox("Roughness")
        self.tri = QCheckBox("Ruggedness (TRI)")
        self.tpi = QCheckBox("Topographic position (TPI)")
        self.contours = QCheckBox("Contours every")
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.1, 2000)
        self.interval.setValue(10)
        self.interval.setSuffix(" m")
        grid.addWidget(self.hillshade, 0, 0)
        grid.addWidget(self.hs_multi, 0, 1)
        grid.addWidget(self.zf, 0, 2)
        grid.addWidget(self.slope, 1, 0)
        grid.addWidget(self.slope_unit, 1, 1)
        grid.addWidget(self.aspect, 2, 0)
        grid.addWidget(self.rough, 2, 1)
        grid.addWidget(self.tri, 3, 0)
        grid.addWidget(self.tpi, 3, 1, 1, 2)
        grid.addWidget(self.contours, 4, 0)
        grid.addWidget(self.interval, 4, 1)
        lay.addWidget(self.deriv_box)

        g = QGroupBox("Styling")
        sl = QFormLayout(g)
        self.style = QComboBox()
        self.style.addItem("Hypsometric colour ramp", "elevation")
        self.style.addItem("Hillshade renderer", "hillshade")
        self.style.addItem("Plain greyscale", "grey")
        idx = self.style.findData(settings.get("dem_style"))
        self.style.setCurrentIndex(max(0, idx))
        sl.addRow("DEM style", self.style)
        self.blend = QCheckBox("Blend a hillshade over the colours")
        self.blend.setChecked(settings.get("dem_blend_hillshade"))
        sl.addRow("", self.blend)
        lay.addWidget(g)
        lay.addStretch(1)

        # ------------------------------------------------ footer
        foot = QFrame()
        foot.setObjectName("Detail")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(8, 6, 8, 6)
        self.estimate = QLabel("")
        self.estimate.setObjectName("Muted")
        self.estimate.setWordWrap(True)
        fl.addWidget(self.estimate)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        fl.addWidget(self.progress)
        self.log = QLabel("")
        self.log.setObjectName("Hint")
        self.log.setVisible(False)
        fl.addWidget(self.log)
        brow = QHBoxLayout()
        self.cancel = QPushButton("Cancel")
        self.cancel.setObjectName("Ghost")
        self.cancel.setVisible(False)
        self.run_btn = QPushButton(theme.icon("download", "#ffffff"), "Get elevation")
        self.run_btn.setObjectName("Primary")
        brow.addWidget(self.cancel)
        brow.addWidget(self.run_btn, 1)
        fl.addLayout(brow)
        outer.addWidget(foot)

        # wiring
        for w in (self.source,):
            w.currentIndexChanged.connect(self._source_changed)
        for sig in (self.aoi.changed, self.res_mode.currentIndexChanged, self.res.valueChanged,
                    self.max_mb.valueChanged, self.download.toggled, self.dtm.toggled):
            sig.connect(self._update)
        self.style.currentIndexChanged.connect(lambda *_: settings.set("dem_style", self.style.currentData()))
        self.blend.toggled.connect(lambda v: settings.set("dem_blend_hillshade", v))
        self.max_mb.valueChanged.connect(lambda v: settings.set("dem_max_mb", v))
        self.run_btn.clicked.connect(self.run)
        self.cancel.clicked.connect(self._cancel)
        self._source_changed()

    # ------------------------------------------------------------------ state
    def select_source(self, source_id):
        idx = self.source.findData(source_id)
        if idx >= 0:
            self.source.setCurrentIndex(idx)

    def _source_changed(self):
        sid = self.source.currentData()
        if sid == AUTO:
            self.dtm.setEnabled(True)
            self.dsm.setEnabled(True)
            self.source_info.setText("Tries HRDEM 1 m lidar → MRDEM 30 m (Canada) → USGS 3DEP 10 m (US) → "
                                     "Copernicus 30 m, using the first with data in your area.")
            multi = False
        else:
            s = SOURCES_BY_ID[sid]
            self.dtm.setEnabled("dtm" in s.assets)
            self.dsm.setEnabled("dsm" in s.assets)
            if not self.dtm.isEnabled():
                self.dsm.setChecked(True)
            if not self.dsm.isEnabled():
                self.dtm.setChecked(True)
            self.source_info.setText(f"{s.description}  {s.resolution:g} m · {s.coverage_label} · {s.license}")
            multi = s.multi_project
            self.res.setValue(max(self.res.minimum(), s.resolution))
        self.lidar.setVisible(multi)
        self.lidar_lbl.setVisible(multi)
        self._update()

    def _native_res(self, bbox):
        sid = self.source.currentData()
        if sid != AUTO:
            return SOURCES_BY_ID[sid].resolution
        cands = candidate_sources(bbox, "dtm") if bbox else []
        return cands[0].resolution if cands else 30

    def _update(self):
        stream = self.stream.isChecked()
        self.deriv_box.setEnabled(not stream)
        self.compression.setEnabled(not stream)
        self.res.setEnabled(self.res_mode.currentData() == "custom")
        bbox = self.aoi.bbox_ll()
        sid = self.source.currentData()
        if not bbox:
            self.estimate.setText("Choose an area to estimate the size.")
            self.run_btn.setEnabled(False)
            return
        if sid != AUTO and not bbox_intersects(SOURCES_BY_ID[sid].coverage, bbox):
            self.estimate.setText(f"⚠ {SOURCES_BY_ID[sid].title} doesn't cover this area.")
            self.run_btn.setEnabled(False)
            return
        self.run_btn.setEnabled(self.task is None)
        area = bbox_area_km2(bbox)
        native = self._native_res(bbox)
        if self.res_mode.currentData() == "custom":
            res = self.res.value()
        else:
            res = fit_resolution(area, native, self.max_mb.value())
        mb = estimate_mb(area, res)
        extra = ""
        if res != native and self.res_mode.currentData() == "auto":
            extra = f" (native {native:g} m would be ~{estimate_mb(area, native):,.0f} MB)"
        if stream:
            self.estimate.setText(f"Streams {area:,.1f} km² at {res:g} m — nothing is downloaded up front.")
        else:
            warn = "⚠ " if mb > self.max_mb.value() else ""
            self.estimate.setText(f"{warn}{area:,.1f} km² at {res:g} m ≈ {mb:,.1f} MB{extra}")
        self.run_btn.setText("Stream elevation" if stream else "Get elevation")

    # ------------------------------------------------------------------ run
    def build_request(self):
        bbox = self.aoi.bbox_ll()
        crs = self.crs.crs()
        if not crs.isValid():
            crs = QgsCoordinateReferenceSystem("EPSG:3857")
        rect = self.aoi.bounds_in(crs)
        sid = self.source.currentData()
        surface = "dsm" if self.dsm.isChecked() else "dtm"
        return DemRequest(
            source_id=sid, surface=surface, bbox_ll=bbox, target_crs_wkt=crs.toWkt(),
            target_bounds=(rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()),
            target_is_geographic=crs.isGeographic(),
            resolution=self.res.value() if self.res_mode.currentData() == "custom" else None,
            resampling=self.resampling.currentText(), mode="stream" if self.stream.isChecked() else "download",
            out_dir=self.folder.filePath() or os.path.join(settings.download_dir(), "dem"),
            name=safe_name(self.name.text()) if self.name.text().strip() else "",
            compression=self.compression.currentText(), max_mb=self.max_mb.value(),
            lidar_strategy=self.lidar.currentData(),
            hillshade=self.hillshade.isChecked(), hillshade_multi=self.hs_multi.isChecked(), z_factor=self.zf.value(),
            slope=self.slope.isChecked(), slope_percent=self.slope_unit.currentIndex() == 1,
            aspect=self.aspect.isChecked(), roughness=self.rough.isChecked(), tri=self.tri.isChecked(),
            tpi=self.tpi.isChecked(), contours=self.contours.isChecked(), contour_interval=self.interval.value(),
        )

    def run(self):
        req = self.build_request()
        if not req.bbox_ll:
            return
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.log.setVisible(True)
        self.log.setText("Starting…")
        self.cancel.setVisible(True)
        self.run_btn.setEnabled(False)
        self.actions.run_dem(req, on_done=self._done, on_task=self._attach)

    def _attach(self, task):
        self.task = task
        # progressChanged is queued onto the main thread; use it to surface the builder's latest log line too
        task.progressChanged.connect(lambda p: (self.progress.setValue(int(p)),
                                                task.messages and self.log.setText(task.messages[-1])))

    def _done(self, ok, result, error):
        self.task = None
        self.progress.setVisible(False)
        self.cancel.setVisible(False)
        self.run_btn.setEnabled(True)
        if error:
            self.log.setText(f"⚠ {error}")
        elif not ok:
            self.log.setText("Canceled.")
        else:
            lines = [f"✓ {result.source.title}, {result.tiles} tile(s), {result.resolution:g} m → "
                     f"{os.path.basename(result.dem_path)}"] + result.messages
            self.log.setText("\n".join(lines))
        self._update()

    def _cancel(self):
        if self.task:
            self.task.cancel()
