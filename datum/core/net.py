# SPDX-License-Identifier: GPL-2.0-or-later
"""Tiny HTTP layer.

Inside QGIS requests go through QgsBlockingNetworkRequest so the user's proxy,
SSL and authentication settings are honoured. Outside QGIS (unit tests, CLI)
it falls back to urllib. All calls are blocking: run them from a QgsTask.
"""

import json
import threading
import time
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

try:  # pragma: no cover - exercised inside QGIS only
    from qgis.core import QgsBlockingNetworkRequest
    from qgis.PyQt.QtCore import QUrl, QByteArray
    from qgis.PyQt.QtNetwork import QNetworkRequest
    HAVE_QGIS = True
except ImportError:
    HAVE_QGIS = False

USER_AGENT = "Datum-QGIS-Plugin/1.0 (+https://github.com/thomasloydon/qgis-datum)"
DEFAULT_TIMEOUT = 30


class NetworkError(Exception):
    pass


def with_params(url, params=None):
    """Merge ``params`` into the query string of ``url``."""
    if not params:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for k, v in params.items():
        if v is None:
            continue
        query[k] = v if isinstance(v, str) else (json.dumps(v) if isinstance(v, (list, dict)) else str(v))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class _Cache:
    def __init__(self, ttl=600, max_items=256):
        self.ttl = ttl
        self.max_items = max_items
        self._data = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._data.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
            return None

    def put(self, key, value):
        with self._lock:
            if len(self._data) >= self.max_items:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (time.time(), value)

    def clear(self):
        with self._lock:
            self._data.clear()


cache = _Cache()
_timeout = DEFAULT_TIMEOUT


def set_timeout(seconds):
    global _timeout
    _timeout = max(5, int(seconds))


def _fetch_qgis(url, data=None, headers=None, timeout=None):  # pragma: no cover
    req = QNetworkRequest(QUrl(url))
    req.setRawHeader(b"User-Agent", USER_AGENT.encode())
    for k, v in (headers or {}).items():
        req.setRawHeader(k.encode(), v.encode())
    try:
        req.setTransferTimeout(int((timeout or _timeout) * 1000))
    except AttributeError:
        pass
    blocking = QgsBlockingNetworkRequest()
    if data is not None:
        if not (headers or {}).get("Content-Type"):
            req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        err = blocking.post(req, QByteArray(data))
    else:
        err = blocking.get(req, forceRefresh=False)
    reply = blocking.reply()
    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
    if err != QgsBlockingNetworkRequest.ErrorCode.NoError:
        raise NetworkError(f"{blocking.errorMessage()} ({url})")
    if status and int(status) >= 400:
        raise NetworkError(f"HTTP {status} for {url}")
    return bytes(reply.content())


def _fetch_urllib(url, data=None, headers=None, timeout=None):
    import urllib.request
    import urllib.error
    h = {"User-Agent": USER_AGENT}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        # fetch() only lets http(s) URLs through, so file:// and custom schemes can't reach here
        with urllib.request.urlopen(req, timeout=timeout or _timeout) as resp:  # nosec B310
            return resp.read()
    except urllib.error.HTTPError as e:
        raise NetworkError(f"HTTP {e.code} for {url}") from e
    except (urllib.error.URLError, OSError) as e:
        raise NetworkError(f"{e} ({url})") from e


def fetch(url, params=None, data=None, headers=None, timeout=None, use_cache=True):
    """GET (or POST when ``data`` is given) and return the body as bytes."""
    full = with_params(url, params)
    scheme = urlsplit(full).scheme.lower()
    if scheme not in ("http", "https"):
        # never let a catalogue record or pasted URL read local files (file://) or odd schemes
        raise NetworkError(f"Unsupported URL scheme '{scheme or '(none)'}': {full}")
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
    key = (full, data)
    if use_cache:
        hit = cache.get(key)
        if hit is not None:
            return hit
    impl = _fetch_qgis if HAVE_QGIS else _fetch_urllib
    body = impl(full, data=data, headers=headers, timeout=timeout)
    if use_cache:
        cache.put(key, body)
    return body


def fetch_json(url, params=None, data=None, **kw):
    body = fetch(url, params=params, data=data, **kw)
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise NetworkError(f"Response from {url} was not JSON") from e
