#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Release helpers for CI (stdlib only).

    scripts/release.py check [--tag v1.2.3] [--publishable]   validate metadata.txt
    scripts/release.py version                                print the plugin version
    scripts/release.py zip [--out dist]                       build the installable zip
    scripts/release.py publish dist/datum-1.2.3.zip           upload to plugins.qgis.org

``publish`` reads OSGEO_USERNAME / OSGEO_PASSWORD from the environment.
"""

import argparse
import configparser
import os
import re
import sys
import xmlrpc.client
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = "datum"
METADATA = os.path.join(ROOT, PLUGIN, "metadata.txt")

REQUIRED = ["name", "qgisMinimumVersion", "description", "about", "version", "author", "email"]
# plugins.qgis.org rejects uploads without these
REQUIRED_TO_PUBLISH = ["repository", "tracker"]
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}
EXCLUDE_EXT = {".pyc", ".pyo"}


def metadata():
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str  # keys are case-sensitive (qgisMinimumVersion)
    with open(METADATA, encoding="utf-8") as f:
        cp.read_file(f)
    return dict(cp["general"])


def check(tag=None, publishable=False):
    md = metadata()
    errors = [f"metadata.txt: missing '{k}'" for k in REQUIRED if not md.get(k, "").strip()]
    if publishable:
        errors += [f"metadata.txt: '{k}' is required by plugins.qgis.org" for k in REQUIRED_TO_PUBLISH
                   if not md.get(k, "").strip()]
        if "noreply" in md.get("email", ""):
            errors.append("metadata.txt: plugins.qgis.org needs a real contact email, not a noreply address")
    version = md.get("version", "")
    if version and not re.fullmatch(r"\d+\.\d+\.\d+([.-]?(alpha|beta|rc)\d*)?", version):
        errors.append(f"version '{version}' is not semver-like (e.g. 1.2.3 or 1.2.3-rc1)")
    if tag is not None:
        expected = tag[1:] if tag.startswith("v") else tag
        if expected != version:
            errors.append(f"tag '{tag}' does not match metadata version '{version}' — bump metadata.txt first")
    if version and f"{version}" not in md.get("changelog", ""):
        print(f"warning: changelog in metadata.txt has no entry for {version}", file=sys.stderr)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    if not errors:
        print(f"metadata OK: {md['name']} {version}")
    return not errors


def build_zip(out_dir):
    version = metadata()["version"]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{PLUGIN}-{version}.zip")
    src = os.path.join(ROOT, PLUGIN)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
            for name in sorted(filenames):
                if os.path.splitext(name)[1] in EXCLUDE_EXT or name == ".DS_Store":
                    continue
                full = os.path.join(dirpath, name)
                # QGIS requires the zip to contain a single top-level folder named like the plugin
                zf.write(full, os.path.relpath(full, ROOT))
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    tops = {n.split("/")[0] for n in names}
    assert tops == {PLUGIN}, f"zip must contain only '{PLUGIN}/', got {tops}"
    assert f"{PLUGIN}/metadata.txt" in names and f"{PLUGIN}/__init__.py" in names
    print(path)
    return path


def publish(zip_path):
    user, password = os.environ.get("OSGEO_USERNAME"), os.environ.get("OSGEO_PASSWORD")
    if not user or not password:
        print("error: set OSGEO_USERNAME and OSGEO_PASSWORD", file=sys.stderr)
        return False
    from urllib.parse import quote
    endpoint = f"https://{quote(user, safe='')}:{quote(password, safe='')}@plugins.qgis.org/plugins/RPC2/"
    server = xmlrpc.client.ServerProxy(endpoint, verbose=False)
    with open(zip_path, "rb") as f:
        data = xmlrpc.client.Binary(f.read())
    try:
        plugin_id, version_id = server.plugin.upload(data)
    except xmlrpc.client.ProtocolError as e:
        # never echo the URL: it contains the credentials
        print(f"error: plugins.qgis.org returned HTTP {e.errcode} {e.errmsg}", file=sys.stderr)
        return False
    except xmlrpc.client.Fault as e:
        print(f"error: plugins.qgis.org rejected the upload: {e.faultString}", file=sys.stderr)
        return False
    print(f"published: plugin {plugin_id}, version {version_id}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--tag")
    c.add_argument("--publishable", action="store_true")
    sub.add_parser("version")
    z = sub.add_parser("zip")
    z.add_argument("--out", default=os.path.join(ROOT, "dist"))
    p = sub.add_parser("publish")
    p.add_argument("zip")
    a = ap.parse_args()
    if a.cmd == "check":
        return 0 if check(a.tag, a.publishable) else 1
    if a.cmd == "version":
        print(metadata()["version"])
        return 0
    if a.cmd == "zip":
        build_zip(a.out)
        return 0
    if a.cmd == "publish":
        return 0 if publish(a.zip) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
