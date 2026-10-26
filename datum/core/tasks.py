# SPDX-License-Identifier: GPL-2.0-or-later
"""Run blocking work in QGIS's task manager and hand results back on the main thread."""

import traceback

from qgis.core import QgsApplication, QgsTask, QgsMessageLog, Qgis

from .dem import Canceled

_running = set()   # keep Python wrappers alive until the task finishes
LOG_TAG = "Datum"


def log(msg, level=Qgis.MessageLevel.Info):
    QgsMessageLog.logMessage(str(msg), LOG_TAG, level)


class FnTask(QgsTask):
    def __init__(self, description, fn, done, can_cancel=True, silent=False):
        flags = QgsTask.Flag.CanCancel if can_cancel else QgsTask.Flag(0)
        if silent:
            try:
                flags |= QgsTask.Flag.Silent
            except AttributeError:
                pass
        super().__init__(description, flags)
        self.fn = fn
        self.done = done
        self.result = None
        self.error = None
        self.messages = []

    # feedback protocol used by DemBuilder
    def canceled(self):
        return self.isCanceled()

    def progress(self, pct):
        self.setProgress(max(0.0, min(100.0, float(pct))))

    def log(self, msg):
        self.messages.append(msg)
        log(msg)

    def run(self):
        try:
            self.result = self.fn(self)
            return not self.isCanceled()
        except Canceled:
            return False
        except Exception as e:  # noqa: BLE001 - reported to the UI
            self.error = e
            log(traceback.format_exc(), Qgis.MessageLevel.Warning)
            return False

    def finished(self, ok):
        _running.discard(self)
        if self.done:
            try:
                self.done(ok, self.result, self.error)
            except Exception:  # noqa: BLE001
                log(traceback.format_exc(), Qgis.MessageLevel.Critical)


def run(description, fn, done=None, can_cancel=True, silent=False):
    """Start ``fn(task)`` in the background. ``done(ok, result, error)`` runs on the main thread."""
    task = FnTask(description, fn, done, can_cancel, silent)
    _running.add(task)
    QgsApplication.taskManager().addTask(task)
    return task
