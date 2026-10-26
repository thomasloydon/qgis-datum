# SPDX-License-Identifier: GPL-2.0-or-later
def classFactory(iface):  # noqa: N802 - QGIS entry point
    from .plugin import DatumPlugin
    return DatumPlugin(iface)
