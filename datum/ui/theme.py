# SPDX-License-Identifier: GPL-2.0-or-later
"""Palette-aware colours, the stylesheet and tintable line icons."""

from functools import lru_cache

from qgis.PyQt.QtCore import Qt, QByteArray, QRectF
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap, QPalette, QGuiApplication
from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt.QtSvg import QSvgRenderer

from ..core.models import Kind

# 24x24 stroke icons (Lucide-style, MIT)
ICON_PATHS = {
    "search": '<circle cx="11" cy="11" r="7.5"/><path d="m21 21-4.6-4.6"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "mountain": '<path d="m8 3 4 8 5-5 5 15H2L8 3z"/>',
    "map": '<path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15"/><path d="M15 6v15"/>',
    "satellite": '<path d="M13 7 9 3 5 7l4 4"/><path d="m17 11 4 4-4 4-4-4"/><path d="m8 12 4 4 6-6-4-4z"/>'
                 '<path d="m16 8 3-3"/><path d="M9 21a6 6 0 0 0-6-6"/>',
    "water": '<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 '
             '13 5 15a7 7 0 0 0 7 7z"/>',
    "road": '<path d="M4 22 8 2"/><path d="M20 22 16 2"/><path d="M12 5v2"/><path d="M12 11v2"/><path d="M12 17v2"/>',
    "boundary": '<path d="M4 4h16v16H4z" stroke-dasharray="3 2.5"/>',
    "parcel": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 12h18"/><path d="M12 3v18"/>',
    "tree": '<path d="m12 2-6 9h4l-5 7h14l-5-7h4z"/><path d="M12 18v4"/>',
    "fire": '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.4-.5-2-1-3-1.1-2.1-.2-4 2-6 .5 2.5 2 4.9 4 '
            '6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.2.4-2.3 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
    "rock": '<path d="M6 3h12l4 6-10 13L2 9z"/><path d="M2 9h20"/><path d="m12 22 4-13-3-6"/>'
            '<path d="m12 22-4-13 3-6"/>',
    "pin": '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
    "star": '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8-6.2-3.2-6.2 3.2L7 14.2 2 9.3l6.9-1z"/>',
    "star-filled": '<path fill="{c}" d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8-6.2-3.2-6.2 3.2L7 14.2 2 9.3l6.9-1z"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/>'
            '<path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    "settings": '<path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M20 21v-5"/>'
                '<path d="M20 12V3"/><path d="M1 14h6"/><path d="M9 8h6"/><path d="M17 16h6"/>',
    "history": '<path d="M3 12a9 9 0 1 0 9-9 9.8 9.8 0 0 0-6.7 2.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    "external": '<path d="M15 3h6v6"/><path d="M10 14 21 3"/>'
                '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/>'
             '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "extent": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
              '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/>'
              '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="2"/>',
    "draw": '<rect x="3" y="3" width="18" height="18" rx="1" stroke-dasharray="4 3"/><path d="M12 8v8M8 12h8"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
             '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/>'
            '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/>'
                '<path d="M3 12a9 3 0 0 0 18 0"/>',
    "zap": '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "filter": '<path d="M22 3H2l8 9.5V19l4 2v-8.5z"/>',
    "vector": '<circle cx="5" cy="19" r="2"/><circle cx="19" cy="5" r="2"/><path d="M6.5 17.5 17.5 6.5"/>',
    "folder": '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9l-.8-1.2A2 2 0 0 0 '
              '7.9 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z"/>',
    "url": '<path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 1 1 0 10h-2"/><path d="M8 12h8"/>',
    "logo": '<circle cx="12" cy="12" r="9.5"/><path d="M12 1v4M12 19v4M1 12h4M19 12h4"/>'
            '<path d="m6.5 16 3.5-6 2.5 3.5L14 11l3.5 5z" fill="{c}" stroke-linejoin="round"/>',
}

KIND_COLORS = {
    Kind.WFS: "#2f80ed", Kind.WMS: "#8e5bd8", Kind.WMTS: "#8e5bd8", Kind.XYZ: "#7a6ff0",
    Kind.ARCGIS_FEATURE: "#1f9d8a", Kind.ARCGIS_MAP: "#1f9d8a", Kind.ARCGIS_IMAGE: "#1f9d8a",
    Kind.COG: "#d9822b", Kind.RASTER_FILE: "#d9822b", Kind.VECTOR_FILE: "#2f80ed",
    Kind.STAC_COLLECTION: "#c2553d", Kind.DEM: "#3a8f3f", Kind.LINK: "#8a8f98",
}

SOURCE_COLORS = {
    "curated": "#d4a017", "bcdc": "#1f5aa6", "opencanada": "#c8102e", "nrcan_stac": "#26734d",
    "earth_search": "#ff9900", "planetary": "#0078d4",
}


def is_dark():
    pal = QApplication.palette() if QApplication.instance() else QGuiApplication.palette()
    return pal.color(QPalette.ColorRole.Window).lightness() < 128


def accent():
    return QColor("#3fbfa4") if is_dark() else QColor("#0f7a68")


def muted():
    pal = QApplication.palette()
    c = pal.color(QPalette.ColorRole.WindowText)
    c.setAlphaF(0.62)
    return c


def source_color(source_id):
    return QColor(SOURCE_COLORS.get(source_id, "#6b7280"))


@lru_cache(maxsize=512)
def _icon(name, color, size):
    body = ICON_PATHS.get(name, ICON_PATHS["info"]).replace("{c}", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    icon = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        renderer.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def icon(name, color=None, size=18):
    if color is None:
        color = QApplication.palette().color(QPalette.ColorRole.WindowText).name()
    elif isinstance(color, QColor):
        color = color.name()
    return _icon(name, color, size)


def accent_icon(name, size=18):
    return icon(name, accent().name(), size)


def stylesheet():
    pal = QApplication.palette()
    dark = is_dark()
    a = accent().name()
    base = pal.color(QPalette.ColorRole.Base)
    window = pal.color(QPalette.ColorRole.Window)
    text = pal.color(QPalette.ColorRole.WindowText).name()
    border = QColor(text)
    border.setAlphaF(0.16)
    border_css = f"rgba({border.red()},{border.green()},{border.blue()},0.16)"
    soft = QColor(a)
    soft_css = f"rgba({soft.red()},{soft.green()},{soft.blue()},{0.22 if dark else 0.12})"
    card = base.lighter(112).name() if dark else base.name()
    header_bg = window.darker(108).name() if not dark else window.lighter(118).name()
    return f"""
    #DatumRoot {{ background: {window.name()}; }}
    #DatumHeader {{ background: {header_bg}; border-bottom: 1px solid {border_css}; }}
    #DatumTitle {{ font-size: 15px; font-weight: 700; }}
    #DatumSubtitle {{ color: {muted().name(QColor.NameFormat.HexArgb)}; font-size: 11px; }}
    QTabWidget#DatumTabs::pane {{ border: none; }}
    QTabWidget#DatumTabs > QTabBar::tab {{ padding: 6px 10px; margin: 0 1px; border: none;
        border-bottom: 2px solid transparent; }}
    QTabWidget#DatumTabs > QTabBar::tab:selected {{ border-bottom: 2px solid {a}; font-weight: 600; }}
    QTabWidget#DatumTabs > QTabBar::tab:hover:!selected {{ background: {soft_css}; }}
    QLineEdit#DatumSearch {{ padding: 6px 8px; border-radius: 7px; border: 1px solid {border_css};
        background: {card}; font-size: 13px; }}
    QLineEdit#DatumSearch:focus {{ border: 1px solid {a}; }}
    QPushButton#Primary {{ background: {a}; color: white; border: none; border-radius: 6px;
        padding: 6px 14px; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {QColor(a).lighter(112).name()}; }}
    QPushButton#Primary:disabled {{ background: {border_css}; color: {muted().name(QColor.NameFormat.HexArgb)}; }}
    QPushButton#Ghost, QToolButton#Ghost {{ border: 1px solid {border_css}; border-radius: 6px; padding: 4px 9px;
        background: transparent; }}
    QPushButton#Ghost:hover, QToolButton#Ghost:hover {{ background: {soft_css}; border-color: {a}; }}
    QToolButton#Chip {{ border: 1px solid {border_css}; border-radius: 11px; padding: 2px 9px; }}
    QToolButton#Chip:checked {{ background: {soft_css}; border-color: {a}; color: {a}; font-weight: 600; }}
    QListView#Results, QTreeWidget#Catalog, QListWidget#Library {{ border: none; background: {window.name()}; }}
    QFrame#Card {{ background: {card}; border: 1px solid {border_css}; border-radius: 8px; }}
    QFrame#Detail {{ background: {card}; border-top: 1px solid {border_css}; }}
    QLabel#SectionTitle {{ font-weight: 700; font-size: 12px; color: {a}; }}
    QLabel#Muted {{ color: {muted().name(QColor.NameFormat.HexArgb)}; }}
    QLabel#Hint {{ color: {muted().name(QColor.NameFormat.HexArgb)}; font-size: 11px; }}
    QGroupBox {{ font-weight: 600; border: 1px solid {border_css}; border-radius: 8px; margin-top: 10px;
        padding: 8px 6px 6px 6px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {a}; }}
    QProgressBar {{ border: none; border-radius: 3px; background: {border_css}; max-height: 6px; text-align: center; }}
    QProgressBar::chunk {{ background: {a}; border-radius: 3px; }}
    """
