#!/usr/bin/env python3
"""Executive Presentation Studio – web server.

Serves the browser app from ./static and the JSON API under /api/.
Python 3.11. The server itself uses only the standard library; python-pptx and
pypdf are optional and switch on corporate templates, native charts, deck
transformation and PDF reading.

    py -3.11 server.py                 Windows (or: .venv\\Scripts\\python server.py)
    python3 server.py                  Linux/macOS
"""
import json
import logging
import mimetypes
import signal
import socket
import ssl
import sys
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from studio import catalog, config, tls
from studio.extract import ExtractError
from studio.schema import BadRequest
from studio.services import Studio

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_JSON_BYTES = 4 * 1024 * 1024

log = logging.getLogger("studio")

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                               "script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "ExecStudio/1.0"
    protocol_version = "HTTP/1.1"
    timeout = 60                 # seconds a connection may sit idle (also bounds the TLS handshake)
    studio: Studio = None        # set in build_server()
    extra_headers = {}           # HSTS when serving HTTPS

    def setup(self):
        # The TLS handshake runs here, in the connection's own thread, so one slow or
        # broken client can never block the server from accepting others.
        self.request.settimeout(self.timeout)
        if isinstance(self.request, ssl.SSLSocket):
            self.request.do_handshake()
        super().setup()

    # ------------------------------------------------------------ routing
    GET_ROUTES = {
        "/api/health": lambda s, q: s.health(),
        "/api/meta": lambda s, q: s.meta(),
        "/api/repository": lambda s, q: catalog.repository(),
        "/api/toolkit": lambda s, q: catalog.toolkit(),
    }
    POST_JSON_ROUTES = {
        "/api/storyline": "storyline",
        "/api/review": "review",
        "/api/qa": "qa",
        "/api/advise": "advise",
        "/api/sharpen": "sharpen",
        "/api/deck/transform": "deck_transform",
    }

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in self.GET_ROUTES:
            return self._guard(lambda: self._json(self.GET_ROUTES[path](self.studio, None)))
        if path.startswith("/api/download/"):
            fid = path.rsplit("/", 1)[-1]
            return self._guard(lambda: self._file(*self.studio.download(fid), ctype=_ctype_for(fid, self.studio)))
        if path.startswith("/api/"):
            return self._error(HTTPStatus.NOT_FOUND, "Unknown API endpoint.")
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        return self._error(HTTPStatus.NOT_FOUND, "Page not found.")

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path in self.POST_JSON_ROUTES:
            method = getattr(self.studio, self.POST_JSON_ROUTES[path])
            return self._guard(lambda: self._json(method(self._read_json())))
        if path == "/api/extract":
            return self._guard(self._extract)
        if path == "/api/deck/upload":
            return self._guard(self._deck_upload)
        if path == "/api/export/pptx":
            return self._guard(lambda: self._file(*self.studio.export_pptx(self._read_json()),
                                                  ctype="application/vnd.openxmlformats-officedocument.presentationml.presentation"))
        if path == "/api/export/briefing":
            return self._guard(lambda: self._file(*self.studio.export_briefing(self._read_json()),
                                                  ctype="text/markdown; charset=utf-8"))
        self.close_connection = True  # the unread request body must not leak into the next request
        return self._error(HTTPStatus.NOT_FOUND, "Unknown API endpoint.")

    # ------------------------------------------------------------ handlers
    def _extract(self):
        limit = int(self.studio.cfg["max_upload_mb"]) * 1024 * 1024
        data = self._read_body(limit, "The file is larger than %d MB." % self.studio.cfg["max_upload_mb"])
        name = urllib.parse.unquote(self.headers.get("X-Filename", "upload"))
        self._json(self.studio.extract(name, data))

    def _deck_upload(self):
        limit = int(self.studio.cfg["max_upload_mb"]) * 1024 * 1024
        data = self._read_body(limit, "The file is larger than %d MB." % self.studio.cfg["max_upload_mb"])
        name = urllib.parse.unquote(self.headers.get("X-Filename", "deck.pptx"))
        self._json(self.studio.deck_upload(name, data))

    def _guard(self, fn):
        try:
            fn()
        except (BadRequest, ExtractError) as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
        except _TooLarge as e:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, str(e))
        except Exception:  # noqa: BLE001
            log.exception("Unhandled error on %s", self.path)
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Something went wrong on the server. The details are in the server log.")

    # ------------------------------------------------------------ I/O
    def _read_body(self, limit, too_large_msg):
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            # drain so the connection stays usable, then refuse
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            raise _TooLarge(too_large_msg)
        return self.rfile.read(length) if length else b""

    def _read_json(self):
        raw = self._read_body(MAX_JSON_BYTES, "The request is too large.")
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError) as e:
            raise BadRequest("The request body is not valid JSON.") from e
        if not isinstance(data, dict):
            raise BadRequest("The request body must be a JSON object.")
        return data

    def _send(self, status, body, ctype, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        for k, v in self.extra_headers.items():
            self.send_header(k, v)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status=HTTPStatus.OK):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _error(self, status, message):
        self._json({"error": message}, status)

    def _file(self, filename, data, ctype):
        ascii_name = filename.encode("ascii", "ignore").decode() or "download"
        disp = 'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (ascii_name.replace('"', ""), urllib.parse.quote(filename))
        self._send(HTTPStatus.OK, data, ctype, {"Content-Disposition": disp, "Cache-Control": "no-store"})

    def _static(self, rel):
        target = (STATIC / urllib.parse.unquote(rel)).resolve()
        if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "File not found.")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        cache = "no-cache" if target.suffix == ".html" else "public, max-age=300"
        self._send(HTTPStatus.OK, target.read_bytes(), ctype, {"Cache-Control": cache})

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


class _TooLarge(Exception):
    pass


class StudioServer(ThreadingHTTPServer):
    """Threaded HTTP(S) server. With an SSL context, each accepted socket is wrapped and its
    handshake deferred to the connection thread (see Handler.setup)."""
    daemon_threads = True

    def __init__(self, addr, handler, ssl_context=None):
        self.ssl_context = ssl_context
        super().__init__(addr, handler)

    def get_request(self):
        sock, addr = self.socket.accept()
        if self.ssl_context is not None:
            sock = self.ssl_context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr

    def handle_error(self, request, client_address):
        err = sys.exc_info()[1]
        if isinstance(err, (ssl.SSLError, ConnectionError, TimeoutError, socket.timeout)):
            # e.g. someone typed http:// on the HTTPS port, or a scanner probed the port
            log.debug("Connection from %s dropped: %s", client_address[0], err)
            return
        log.exception("Error handling request from %s", client_address[0])


class RedirectHandler(BaseHTTPRequestHandler):
    """Plain-HTTP listener that sends every request to the HTTPS address."""
    https_port = 443
    timeout = 15

    def _go(self):
        host = (self.headers.get("Host") or "localhost").split(":")[0]
        port = "" if self.https_port == 443 else ":%d" % self.https_port
        self.send_response(HTTPStatus.MOVED_PERMANENTLY)
        self.send_header("Location", "https://%s%s%s" % (host, port, self.path if self.path.startswith("/") else "/"))
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    do_GET = do_HEAD = do_POST = _go

    def log_message(self, fmt, *args):
        log.debug("redirect %s %s", self.address_string(), fmt % args)


PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _ctype_for(fid, studio):
    try:
        _, name = studio.work.get(fid)
    except KeyError:
        return "application/octet-stream"
    return PPTX_TYPE if name.lower().endswith(".pptx") else "application/octet-stream"


def setup_logging(cfg):
    """Console + UTF-8 log file. The Windows console may not be UTF-8, so never let logging crash on it."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    handlers = [logging.StreamHandler()]
    log_path = cfg.get("server_log")
    if log_path:
        path = Path(log_path) if Path(log_path).is_absolute() else ROOT / log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


def build_server(cfg, port=None):
    """Create the server (HTTPS when tls_enabled). Returns (server, scheme, cert_info).
    Raises tls.TLSConfigError if HTTPS is on but the certificate is missing or not acceptable."""
    Handler.studio = Studio(cfg)
    ctx, info = None, None
    if cfg.get("tls_enabled"):
        ctx, info = tls.build_context(cfg)
        Handler.extra_headers = {"Strict-Transport-Security": "max-age=31536000"}
    else:
        Handler.extra_headers = {}
    server = StudioServer((cfg["host"], int(cfg["port"] if port is None else port)), Handler, ctx)
    return server, ("https" if ctx else "http"), info


def start_redirect(cfg):
    port = int(cfg.get("http_redirect_port") or 0)
    if not port or not cfg.get("tls_enabled"):
        return None
    RedirectHandler.https_port = int(cfg["port"])
    srv = ThreadingHTTPServer((cfg["host"], port), RedirectHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="http-redirect").start()
    log.info("HTTP on port %d redirects to HTTPS on port %s", port, cfg["port"])
    return srv


def main():
    cfg = config.load()
    setup_logging(cfg)
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")
    try:
        server, scheme, cert = build_server(cfg)
    except tls.TLSConfigError as e:
        log.error("HTTPS could not start: %s", e)
        sys.exit(2)
    except OSError as e:
        log.error("Cannot listen on %s:%s (%s). Is another program using the port?", cfg["host"], cfg["port"], e)
        sys.exit(2)
    if cert:
        log.info("Certificate: %s, issued by %s, valid until %s (%s days)%s", cert.get("subject"), cert.get("issuer"),
                 cert["not_after"].date() if cert.get("not_after") else "?", cert.get("days_left", "?"),
                 " SELF-SIGNED - TEST ONLY" if cert.get("self_signed") else "")
        if cert.get("names"):
            log.info("Certificate is valid for: %s", ", ".join(cert["names"]))
        if cert.get("days_left", 999) < 30:
            log.warning("The certificate expires in %s days. Arrange a renewal.", cert["days_left"])
    else:
        log.warning("Serving plain HTTP. Set tls_enabled and a certificate in config.json for the production server.")
    start_redirect(cfg)
    llm = Handler.studio.llm.health()
    log.info("Executive Presentation Studio on %s://%s:%s", scheme, cfg["host"], cfg["port"])
    log.info("LLM %s at %s: %s", cfg["llm_model"], cfg["llm_base_url"],
             "reachable" if llm["reachable"] else "NOT reachable - " + (llm["detail"] or "unknown"))
    st = Handler.studio.health()
    log.info("PowerPoint engine: %s | deck transformation: %s | PDF reading: %s", st["pptx"]["engine"],
             "on" if st["pptx"]["transform"] else "off (install python-pptx)", "on" if st["pdf"] else "off (install pypdf)")
    log.info("Open %s://localhost:%s in a browser (Ctrl+C to stop)", scheme, cfg["port"])
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    if hasattr(signal, "SIGBREAK"):  # Windows: Ctrl+Break and service stop
        signal.signal(signal.SIGBREAK, lambda *a: sys.exit(0))
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
