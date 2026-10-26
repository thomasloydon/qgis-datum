#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Release helpers for CI (stdlib only).

    scripts/release.py check [--tag v1.2.3] [--publishable]   validate metadata.txt
    scripts/release.py version                                print the plugin version
    scripts/release.py zip [--out dist]                       build the installable zip
    scripts/release.py publish dist/datum-1.2.3.zip           upload to plugins.qgis.org

``publish`` uses QGIS_PLUGIN_TOKEN (a per-plugin upload token; works for GitHub-login
accounts) or, failing that, OSGEO_USERNAME / OSGEO_PASSWORD.
"""

import argparse
import configparser
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
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
        # plugins.qgis.org rejects packages without a licence file inside the plugin folder
        zf.write(os.path.join(ROOT, "LICENSE"), f"{PLUGIN}/LICENSE")
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    tops = {n.split("/")[0] for n in names}
    assert tops == {PLUGIN}, f"zip must contain only '{PLUGIN}/', got {tops}"
    for required in ("metadata.txt", "__init__.py", "LICENSE"):
        assert f"{PLUGIN}/{required}" in names, f"zip is missing {PLUGIN}/{required}"
    print(path)
    return path


REPO_URL = "https://plugins.qgis.org"


def publish(zip_path):
    """Upload with a plugin token (GitHub/SSO accounts) or OSGeo credentials (XML-RPC)."""
    token = os.environ.get("QGIS_PLUGIN_TOKEN")
    if token:
        return publish_with_token(zip_path, token)
    user, password = os.environ.get("OSGEO_USERNAME"), os.environ.get("OSGEO_PASSWORD")
    if user and password:
        return publish_with_password(zip_path, user, password)
    print("error: set QGIS_PLUGIN_TOKEN, or OSGEO_USERNAME and OSGEO_PASSWORD", file=sys.stderr)
    return False


def _multipart(fields, files):
    boundary = uuid.uuid4().hex
    out = []
    for name, value in fields.items():
        out += [f"--{boundary}", f'Content-Disposition: form-data; name="{name}"', "", value]
    body = "\r\n".join(out).encode() + (b"\r\n" if out else b"")
    for name, (filename, data, ctype) in files.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                 f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect means the form was accepted; don't follow it


def publish_with_token(zip_path, token, base_url=REPO_URL):
    """POST to /plugins/api/<package>/version/add/ with a per-plugin Bearer token.

    Tokens are created on the plugin's page (Manage › Tokens) once the plugin exists,
    so the very first upload has to go through the website.
    """
    md = metadata()
    fields = {"changelog": md.get("changelog", "")}
    if md.get("experimental", "").strip().lower() == "true":
        fields["experimental"] = "on"
    with open(zip_path, "rb") as f:
        body, ctype = _multipart(fields, {"package": (os.path.basename(zip_path), f.read(), "application/zip")})
    url = f"{base_url}/plugins/api/{PLUGIN}/version/add/"
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": ctype, "User-Agent": "datum-release"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=120) as resp:
            status, page = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # includes the 302 the site answers on success
        with e:
            status, page = e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        print(f"error: could not reach {base_url}: {e.reason}", file=sys.stderr)
        return False
    if 300 <= status < 400:
        print(f"published: {PLUGIN} {md['version']} uploaded; it appears once the QGIS team approves it")
        return True
    if status == 403:
        print("error: plugins.qgis.org refused the token (revoked, or for another plugin)", file=sys.stderr)
        return False
    if status == 404:
        print(f"error: no plugin named '{PLUGIN}' on plugins.qgis.org yet; upload the first version "
              f"by hand at {base_url}/plugins/add/", file=sys.stderr)
        return False
    errors = [re.sub(r"<[^>]+>", " ", e) for e in re.findall(r'<ul class="errorlist[^"]*">(.*?)</ul>', page, re.S)]
    detail = "; ".join(" ".join(e.split()) for e in errors) or f"HTTP {status}"
    print(f"error: plugins.qgis.org rejected the upload: {detail}", file=sys.stderr)
    return False


def publish_with_password(zip_path, user, password):
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
