# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for scripts/release.py: metadata checks, zip layout and the token upload.

The upload is exercised against a local stand-in for plugins.qgis.org that mimics
the real view (qgis/QGIS-Django: plugins.views.version_create_api).
"""

import email.parser
import email.policy
import http.server
import importlib.util
import io
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.join(os.path.dirname(__file__), "..")
spec = importlib.util.spec_from_file_location("release", os.path.join(ROOT, "scripts", "release.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

GOOD_TOKEN = "header.payload.signature"


class FakeRepo(http.server.BaseHTTPRequestHandler):
    received = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path != "/plugins/api/datum/version/add/":  # the only plugin on the fake site
            return self._reply(404, "Not found")
        if self.headers.get("Authorization") != f"Bearer {GOOD_TOKEN}":
            return self._reply(403, "Invalid token")
        msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
        parts = {p.get_param("name", header="content-disposition"): p for p in msg.iter_parts()}
        FakeRepo.received.append(parts)
        package = parts["package"].get_payload(decode=True)
        if not zipfile.is_zipfile(io.BytesIO(package)):
            return self._reply(200, '<form><ul class="errorlist"><li>The <b>package</b> is not a zip file.</li></ul></form>')
        self.send_response(302)
        self.send_header("Location", f"/plugins/{release.PLUGIN}/version/1.0.0/")
        self.end_headers()

    def _reply(self, code, text):
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(text.encode())


class TokenUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), FakeRepo)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def run_upload(self, path, token=GOOD_TOKEN, plugin=None):
        out, err = io.StringIO(), io.StringIO()
        old = release.PLUGIN
        if plugin:
            release.PLUGIN = plugin
        try:
            with redirect_stdout(out), redirect_stderr(err):
                ok = release.publish_with_token(path, token, base_url=self.base)
        finally:
            release.PLUGIN = old
        return ok, out.getvalue() + err.getvalue()

    def real_zip(self):
        with redirect_stdout(io.StringIO()):
            return release.build_zip(self.tmp)

    def test_success_sends_token_package_and_changelog(self):
        ok, text = self.run_upload(self.real_zip())
        self.assertTrue(ok, text)
        self.assertIn("published", text)
        parts = FakeRepo.received[-1]
        self.assertEqual(parts["package"].get_filename(), f"{release.PLUGIN}-{release.metadata()['version']}.zip")
        self.assertIn(release.metadata()["version"], parts["changelog"].get_content())
        self.assertNotIn("experimental", parts)

    def test_bad_token(self):
        ok, text = self.run_upload(self.real_zip(), token="nope")
        self.assertFalse(ok)
        self.assertIn("refused the token", text)

    def test_unknown_plugin_explains_first_upload(self):
        ok, text = self.run_upload(self.real_zip(), plugin="not_there")
        self.assertFalse(ok)
        self.assertIn("/plugins/add/", text)

    def test_form_errors_are_reported(self):
        bad = os.path.join(self.tmp, "bad.zip")
        with open(bad, "wb") as f:
            f.write(b"not a zip")
        ok, text = self.run_upload(bad)
        self.assertFalse(ok)
        self.assertIn("The package is not a zip file.", text)

    def test_publish_prefers_token_and_requires_credentials(self):
        env = {k: os.environ.pop(k, None) for k in ("QGIS_PLUGIN_TOKEN", "OSGEO_USERNAME", "OSGEO_PASSWORD")}
        try:
            with redirect_stderr(io.StringIO()) as err:
                self.assertFalse(release.publish("x.zip"))
            self.assertIn("QGIS_PLUGIN_TOKEN", err.getvalue())
        finally:
            for k, v in env.items():
                if v is not None:
                    os.environ[k] = v


class ZipAndMetadataTests(unittest.TestCase):
    def test_zip_has_single_top_folder_without_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                path = release.build_zip(tmp)
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
        self.assertEqual({n.split("/")[0] for n in names}, {release.PLUGIN})
        self.assertFalse([n for n in names if "__pycache__" in n or n.endswith(".pyc")])

    def test_metadata_is_publishable(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertTrue(release.check(publishable=True))
            self.assertFalse(release.check(tag="v0.0.0-does-not-match"))


if __name__ == "__main__":
    sys.exit(unittest.main())
