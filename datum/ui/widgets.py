# SPDX-License-Identifier: GPL-2.0-or-later
"""Reusable widgets: result cards, area-of-interest picker, small helpers."""

from qgis.PyQt.QtCore import Qt, QAbstractListModel, QModelIndex, QRectF, QSize, pyqtSignal, QPointF
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPalette
from qgis.PyQt.QtWidgets import (
    QStyledItemDelegate, QStyle, QWidget, QHBoxLayout, QVBoxLayout, QComboBox, QToolButton, QLabel,
    QDoubleSpinBox, QFrame,
)
from qgis.core import (
    QgsProject, QgsRectangle, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsMapLayerProxyModel,
    QgsGeometry, QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox, QgsMapToolExtent, QgsRubberBand

from ..core.models import Kind, Dataset
from ..core.dem import bbox_area_km2
from ..core.loader import to_ll
from . import theme

DATASET_ROLE = Qt.ItemDataRole.UserRole + 1


def section(text):
    lbl = QLabel(text.upper())
    lbl.setObjectName("SectionTitle")
    return lbl


def hint(text):
    lbl = QLabel(text)
    lbl.setObjectName("Hint")
    lbl.setWordWrap(True)
    return lbl


def tool_button(icon_name, tip, obj="Ghost", text=""):
    b = QToolButton()
    b.setObjectName(obj)
    b.setIcon(theme.icon(icon_name))
    b.setToolTip(tip)
    b.setAutoRaise(False)
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    return b


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Plain)
    f.setStyleSheet("color: rgba(127,127,127,0.25);")
    return f


# --------------------------------------------------------------------------- results list

class ResultModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.favorites = set()

    def rowCount(self, parent=QModelIndex()):  # noqa: B008 - standard Qt model signature
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        ds = self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return ds.title
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"<b>{ds.title}</b><br>{ds.source_label}<br><br>{ds.description[:400]}"
        if role == DATASET_ROLE:
            return ds
        return None

    def clear(self):
        self.beginResetModel()
        self.items = []
        self.endResetModel()

    def extend(self, datasets):
        seen = {d.key for d in self.items}
        new = [d for d in datasets if d.key not in seen]
        if not new:
            return
        self.beginInsertRows(QModelIndex(), len(self.items), len(self.items) + len(new) - 1)
        self.items.extend(new)
        self.endInsertRows()

    def dataset(self, row):
        return self.items[row] if 0 <= row < len(self.items) else None


class ResultDelegate(QStyledItemDelegate):
    """Paints each dataset as a card: source dot, title, meta, snippet and format chips."""

    PAD = 10
    HEIGHT = 98

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.HEIGHT)

    def paint(self, painter, option, index):
        ds: Dataset = index.data(DATASET_ROLE)
        if ds is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = option.palette
        r = QRectF(option.rect).adjusted(6, 3, -6, -3)
        dark = theme.is_dark()
        base = pal.color(QPalette.ColorRole.Base)
        bg = base.lighter(112) if dark else base
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        acc = theme.accent()
        border = QColor(pal.color(QPalette.ColorRole.WindowText))
        border.setAlphaF(0.13)
        if selected:
            fill = QColor(acc)
            fill.setAlphaF(0.16 if dark else 0.09)
            bg = fill
            border = acc
        elif hover:
            border = QColor(acc)
            border.setAlphaF(0.55)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        painter.fillPath(path, bg)
        painter.setPen(QPen(border, 1.2 if selected else 1))
        painter.drawPath(path)

        x = r.left() + self.PAD
        w = r.width() - 2 * self.PAD
        y = r.top() + 8
        text_col = pal.color(QPalette.ColorRole.Text)
        muted = theme.muted()

        # source dot + label + favourite star
        dot = theme.source_color(ds.source)
        painter.setBrush(dot)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(x + 4, y + 7), 4, 4)
        small = QFont(option.font)
        small.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.5))
        painter.setFont(small)
        painter.setPen(muted)
        meta = ds.source_label
        if ds.organization:
            meta += "  ·  " + ds.organization
        if ds.updated:
            meta += "  ·  " + ds.updated
        if ds.extra.get("coverage"):
            meta += "  ·  " + ds.extra["coverage"]
        fm = QFontMetrics(small)
        star_w = 16 if ds.key in self.model.favorites else 0
        painter.drawText(QRectF(x + 14, y, w - 14 - star_w, 15), Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(meta, Qt.TextElideMode.ElideRight, int(w - 14 - star_w)))
        if star_w:
            theme.icon("star-filled", "#e0a400", 13).paint(painter, int(r.right() - self.PAD - 13), int(y + 1), 13, 13)
        y += 18

        # title
        tf = QFont(option.font)
        tf.setBold(True)
        tf.setPointSizeF(option.font.pointSizeF() + 0.5)
        painter.setFont(tf)
        painter.setPen(text_col)
        tfm = QFontMetrics(tf)
        painter.drawText(QRectF(x, y, w, tfm.height()), Qt.AlignmentFlag.AlignVCenter,
                         tfm.elidedText(ds.title, Qt.TextElideMode.ElideRight, int(w)))
        y += tfm.height() + 2

        # snippet
        painter.setFont(small)
        painter.setPen(muted)
        desc = " ".join(ds.description.split())[:300]
        painter.drawText(QRectF(x, y, w, fm.height() + 1), Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(desc or "No description.", Qt.TextElideMode.ElideRight, int(w)))
        y += fm.height() + 6

        # chips
        cx = x
        chip_font = QFont(small)
        chip_font.setBold(True)
        chip_font.setPointSizeF(max(7.0, small.pointSizeF() - 0.5))
        painter.setFont(chip_font)
        cfm = QFontMetrics(chip_font)
        kinds = ds.kinds or [Kind.LINK]
        for kind in kinds[:6]:
            label = Kind.LABELS.get(kind, kind)
            cw = cfm.horizontalAdvance(label) + 12
            if cx + cw > x + w:
                break
            col = QColor(theme.KIND_COLORS.get(kind, "#888"))
            chip = QRectF(cx, y, cw, 16)
            fill = QColor(col)
            fill.setAlphaF(0.22 if dark else 0.13)
            cp = QPainterPath()
            cp.addRoundedRect(chip, 8, 8)
            painter.fillPath(cp, fill)
            painter.setPen(col.lighter(135) if dark else col.darker(115))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, label)
            cx += cw + 5
        painter.restore()


# --------------------------------------------------------------------------- area of interest

class AoiPicker(QWidget):
    """Choose an area: map extent, a layer's extent, selected features, or a drawn rectangle."""

    changed = pyqtSignal()

    CANVAS, LAYER, SELECTION, DRAWN = range(4)

    def __init__(self, iface, parent=None, show_buffer=True):
        super().__init__(parent)
        self.iface = iface
        self.drawn = None          # (QgsRectangle, crs)
        self._tool = None
        self._prev_tool = None
        self._band = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem(theme.icon("extent"), "Current map extent")
        self.mode.addItem(theme.icon("layers"), "Extent of a layer")
        self.mode.addItem(theme.icon("check"), "Selected features")
        self.mode.addItem(theme.icon("draw"), "Draw a rectangle")
        row.addWidget(self.mode, 1)
        self.draw_btn = tool_button("draw", "Draw a rectangle on the map")
        row.addWidget(self.draw_btn)
        lay.addLayout(row)

        self.layer = QgsMapLayerComboBox()
        self.layer.setFilters(QgsMapLayerProxyModel.Filter.HasGeometry | QgsMapLayerProxyModel.Filter.RasterLayer)
        lay.addWidget(self.layer)

        brow = QHBoxLayout()
        self.buffer = QDoubleSpinBox()
        self.buffer.setRange(0, 100000)
        self.buffer.setDecimals(0)
        self.buffer.setSingleStep(100)
        self.buffer.setSuffix(" m buffer")
        self.buffer.setVisible(show_buffer)
        brow.addWidget(self.buffer)
        self.info = QLabel("")
        self.info.setObjectName("Hint")
        brow.addWidget(self.info, 1)
        lay.addLayout(brow)

        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.layer.layerChanged.connect(lambda *_: self._emit())
        self.buffer.valueChanged.connect(lambda *_: self._emit())
        self.draw_btn.clicked.connect(self.start_drawing)
        if iface:
            iface.mapCanvas().extentsChanged.connect(self._canvas_moved)
        self._mode_changed()

    def _canvas_moved(self):
        if self.mode.currentIndex() == self.CANVAS:
            self._emit()

    def _mode_changed(self):
        m = self.mode.currentIndex()
        self.layer.setVisible(m in (self.LAYER, self.SELECTION))
        self.draw_btn.setVisible(m == self.DRAWN)
        if m == self.DRAWN and self.drawn is None:
            self.start_drawing()
        self._emit()

    def _emit(self):
        bbox = self.bbox_ll()
        if bbox:
            area = bbox_area_km2(bbox)
            self.info.setText(f"≈ {area:,.1f} km²" if area < 100 else f"≈ {area:,.0f} km²")
        else:
            self.info.setText("No area")
        self.changed.emit()

    # ---------------------------------------------------------------- drawing
    def start_drawing(self):
        if not self.iface:
            return
        canvas = self.iface.mapCanvas()
        self._prev_tool = canvas.mapTool()
        self._tool = QgsMapToolExtent(canvas)
        self._tool.extentChanged.connect(self._drawn)
        canvas.setMapTool(self._tool)
        self.iface.messageBar().pushInfo("Datum", "Drag a rectangle on the map to set the area.")

    def _drawn(self, rect):
        canvas = self.iface.mapCanvas()
        if rect.isEmpty():
            return
        self.drawn = (QgsRectangle(rect), canvas.mapSettings().destinationCrs())
        self._show_band()
        if self._prev_tool is not None:
            canvas.setMapTool(self._prev_tool)
        else:
            canvas.unsetMapTool(self._tool)
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(self.DRAWN)
        self.mode.blockSignals(False)
        self._mode_changed()

    def _show_band(self):
        canvas = self.iface.mapCanvas()
        if self._band is None:
            self._band = QgsRubberBand(canvas, QgsWkbTypes.GeometryType.PolygonGeometry)
            c = theme.accent()
            self._band.setStrokeColor(c)
            fill = QColor(c)
            fill.setAlphaF(0.08)
            self._band.setFillColor(fill)
            self._band.setWidth(2)
        rect, crs = self.drawn
        ct = QgsCoordinateTransform(crs, canvas.mapSettings().destinationCrs(), QgsProject.instance())
        self._band.setToGeometry(QgsGeometry.fromRect(ct.transformBoundingBox(rect)), None)

    def clear_band(self):
        if self._band is not None:
            self._band.reset(QgsWkbTypes.GeometryType.PolygonGeometry)

    # ---------------------------------------------------------------- results
    def rect_and_crs(self):
        """Selected area as (QgsRectangle, crs) before buffering, or (None, None)."""
        m = self.mode.currentIndex()
        if m == self.CANVAS and self.iface:
            canvas = self.iface.mapCanvas()
            return canvas.extent(), canvas.mapSettings().destinationCrs()
        if m in (self.LAYER, self.SELECTION):
            lyr = self.layer.currentLayer()
            if lyr is None:
                return None, None
            if m == self.SELECTION and hasattr(lyr, "boundingBoxOfSelected"):
                rect = lyr.boundingBoxOfSelected()
                if rect.isEmpty():
                    return None, None
                return rect, lyr.crs()
            return lyr.extent(), lyr.crs()
        if m == self.DRAWN and self.drawn:
            return self.drawn
        return None, None

    def bbox_ll(self):
        rect, crs = self.rect_and_crs()
        if rect is None or rect.isEmpty():
            return None
        try:
            bbox = to_ll(rect, crs)
        except Exception:  # noqa: BLE001
            return None
        if self.buffer.isVisible() and self.buffer.value() > 0:
            import math
            d = self.buffer.value()
            lat = math.radians((bbox[1] + bbox[3]) / 2)
            dx = d / (111320 * max(0.1, math.cos(lat)))
            dy = d / 110570
            bbox = (bbox[0] - dx, bbox[1] - dy, bbox[2] + dx, bbox[3] + dy)
        return bbox

    def bounds_in(self, crs: QgsCoordinateReferenceSystem):
        """The AOI (with buffer) expressed in ``crs``.

        Transforms the original rectangle directly rather than via the lon/lat
        box, which would inflate it (badly so for rotated projections).
        """
        rect, src = self.rect_and_crs()
        if rect is None or rect.isEmpty():
            return None
        out = QgsRectangle(rect)
        if src != crs:
            out = QgsCoordinateTransform(src, crs, QgsProject.instance()).transformBoundingBox(rect)
        d = self.buffer.value() if self.buffer.isVisible() else 0
        if d > 0:
            out.grow(d / 111320.0 if crs.isGeographic() else d)
        return out
