"""HTTPS tests. A throwaway self-signed certificate is generated for each run (testing only).

    python -m unittest tests.test_https -v
"""
import http.client
import os
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studio import config, tls  # noqa: E402

os.environ.setdefault("STUDIO_LLM_BASE_URL", "http://127.0.0.1:9/v1")
os.environ.setdefault("STUDIO_LLM_TIMEOUT", "2")
os.environ.setdefault("STUDIO_SERVER_LOG", "")
os.environ.setdefault("STUDIO_AUDIT_LOG", str(ROOT / "logs" / "test-audit.log"))
os.environ.setdefault("STUDIO_WORK_DIR", str(ROOT / "work" / "test"))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(tls.HAVE_CRYPTOGRAPHY, "cryptography not installed")
class HTTPS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server as srv
        cls.srv = srv
        cls.tmp = Path(tempfile.mkdtemp(prefix="studio-test-"))
        cls.cert, cls.key = cls.tmp / "cert.pem", cls.tmp / "key.pem"
        tls.make_test_certificate(cls.cert, cls.key, hosts=("localhost", "127.0.0.1"))
        # llm_base_url: a closed local port, so /api/health answers at once instead of depending
        # on whatever real AI endpoint .env points at
        cls.cfg = dict(config.load(), host="127.0.0.1", tls_enabled=True, tls_allow_self_signed=True,
                       tls_cert_file=str(cls.cert), tls_key_file=str(cls.key), tls_pfx_file="",
                       llm_base_url="http://127.0.0.1:9/v1")
        cls.server, scheme, cls.info = srv.build_server(cls.cfg, port=0)
        assert scheme == "https"
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.client_ctx = ssl.create_default_context(cafile=str(cls.cert))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        srv = cls.srv
        srv.Handler.extra_headers = {}

    def get(self, path="/api/health"):
        conn = http.client.HTTPSConnection("127.0.0.1", self.port, context=self.client_ctx, timeout=10)
        conn.request("GET", path)
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r, body

    def test_https_serves_app_with_hsts(self):
        r, body = self.get()
        self.assertEqual(r.status, 200)
        self.assertIn("max-age", r.getheader("Strict-Transport-Security"))
        r, body = self.get("/")
        self.assertIn(b"Executive Presentation Studio", body)
        self.assertTrue(self.info["self_signed"])
        self.assertIn("127.0.0.1", self.info["names"])

    def test_tls_1_1_refused(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.maximum_version = ssl.TLSVersion.TLSv1_1
            ctx.minimum_version = ssl.TLSVersion.TLSv1_1
        except (ValueError, AttributeError):
            self.skipTest("local OpenSSL cannot even offer TLS 1.1")
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw:
            with self.assertRaises((ssl.SSLError, ConnectionError, OSError)):
                with ctx.wrap_socket(raw, server_hostname="127.0.0.1"):
                    pass

    def test_plain_http_on_https_port_does_not_break_server(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            try:
                s.recv(100)
            except OSError:
                pass
        self.assertEqual(self.get()[0].status, 200)

    def test_stalled_client_does_not_block_others(self):
        idle = socket.create_connection(("127.0.0.1", self.port), timeout=5)  # never handshakes
        try:
            t0 = time.time()
            self.assertEqual(self.get()[0].status, 200)
            self.assertLess(time.time() - t0, 5)
        finally:
            idle.close()

    def test_redirect_listener(self):
        port = free_port()
        redirect = self.srv.start_redirect(dict(self.cfg, http_redirect_port=port, port=self.port))
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/static/css/app.css", headers={"Host": "studio.example.local:%d" % port})
            r = conn.getresponse()
            self.assertEqual(r.status, 301)
            self.assertEqual(r.getheader("Location"), "https://studio.example.local:%d/static/css/app.css" % self.port)
        finally:
            redirect.shutdown()
            redirect.server_close()


@unittest.skipUnless(tls.HAVE_CRYPTOGRAPHY, "cryptography not installed")
class CertificateRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="studio-test-"))
        cls.cert, cls.key = cls.tmp / "cert.pem", cls.tmp / "key.pem"
        tls.make_test_certificate(cls.cert, cls.key)

    def test_self_signed_refused_by_default(self):
        with self.assertRaises(tls.TLSConfigError) as cm:
            tls.build_context({"tls_cert_file": str(self.cert), "tls_key_file": str(self.key)})
        self.assertIn("self-signed", str(cm.exception))

    def test_no_certificate_configured(self):
        with self.assertRaises(tls.TLSConfigError) as cm:
            tls.build_context({"tls_enabled": True})
        self.assertIn("no certificate", str(cm.exception))

    def test_missing_file(self):
        with self.assertRaises(tls.TLSConfigError) as cm:
            tls.build_context({"tls_pfx_file": str(self.tmp / "nope.pfx")})
        self.assertIn("does not exist", str(cm.exception))

    def _pfx(self, password):
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, load_pem_private_key, pkcs12
        cert = x509.load_pem_x509_certificate(self.cert.read_bytes())
        key = load_pem_private_key(self.key.read_bytes(), None)
        path = self.tmp / "server.pfx"
        path.write_bytes(pkcs12.serialize_key_and_certificates(b"studio", key, cert, None, BestAvailableEncryption(password.encode())))
        return path

    def test_pfx_with_password_file(self):
        pfx = self._pfx("S3cret!")
        pw = self.tmp / "pfx-password.txt"
        pw.write_text("S3cret!\n", encoding="utf-8")
        ctx, info = tls.build_context({"tls_pfx_file": str(pfx), "tls_pfx_password_file": str(pw), "tls_allow_self_signed": True})
        self.assertIsInstance(ctx, ssl.SSLContext)
        self.assertEqual(info["subject"], "Executive Presentation Studio TEST")
        self.assertFalse(any(self.tmp.glob("studio-tls-*")))  # no key material left in temp

    def test_pfx_wrong_password(self):
        pfx = self._pfx("right")
        with self.assertRaises(tls.TLSConfigError) as cm:
            tls.build_context({"tls_pfx_file": str(pfx), "tls_pfx_password": "wrong", "tls_allow_self_signed": True})
        self.assertIn("password is wrong", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
