# SPDX-License-Identifier: GPL-2.0-or-later
"""Favourites and history, persisted as JSON next to the QGIS profile."""

import json
import os
import time

from .models import Dataset, Resource


class Library:
    MAX_HISTORY = 200

    def __init__(self, folder):
        self.path = os.path.join(folder, "library.json")
        self.favorites = []   # [Dataset dict]
        self.history = []     # [{"time", "dataset": Dataset dict, "resource": Resource dict, "layer_name"}]
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.favorites = data.get("favorites", [])
            self.history = data.get("history", [])
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"favorites": self.favorites, "history": self.history}, f, indent=1)
        os.replace(tmp, self.path)

    # -------------------------------------------------------------- favourites
    def is_favorite(self, ds: Dataset):
        return any(f.get("source") == ds.source and f.get("id") == ds.id for f in self.favorites)

    def toggle_favorite(self, ds: Dataset):
        if self.is_favorite(ds):
            self.favorites = [f for f in self.favorites if not (f.get("source") == ds.source and f.get("id") == ds.id)]
            added = False
        else:
            self.favorites.insert(0, ds.to_dict())
            added = True
        self.save()
        return added

    def favorite_datasets(self):
        return [Dataset.from_dict(f) for f in self.favorites]

    def remove_favorite(self, index):
        del self.favorites[index]
        self.save()

    # -------------------------------------------------------------- history
    def record(self, ds: Dataset, res: Resource, layer_name):
        self.history.insert(0, {"time": time.strftime("%Y-%m-%d %H:%M"), "dataset": ds.to_dict(),
                                "resource": res.to_dict(), "layer_name": layer_name})
        del self.history[self.MAX_HISTORY:]
        self.save()

    def history_entries(self):
        out = []
        for h in self.history:
            try:
                out.append((h["time"], Dataset.from_dict(h["dataset"]), Resource.from_dict(h["resource"]),
                            h.get("layer_name", "")))
            except (KeyError, TypeError):
                continue
        return out

    def clear_history(self):
        self.history = []
        self.save()

    # -------------------------------------------------------------- import / export
    def export_favorites(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"datum_favorites": self.favorites}, f, indent=1)

    def import_favorites(self, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        incoming = data.get("datum_favorites", data if isinstance(data, list) else [])
        keys = {(f.get("source"), f.get("id")) for f in self.favorites}
        n = 0
        for fav in incoming:
            if (fav.get("source"), fav.get("id")) not in keys:
                self.favorites.append(fav)
                n += 1
        self.save()
        return n
