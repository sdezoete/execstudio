"""TESTING ONLY: creates a self-signed certificate in certs\\test-cert.pem + certs\\test-key.pem.

Never use this on the production server; the studio refuses self-signed certificates
unless tls_allow_self_signed is true. Browsers will warn about it, which is expected.

    .venv\\Scripts\\python scripts\\make-test-cert.py              (localhost + this PC's name)
    .venv\\Scripts\\python scripts\\make-test-cert.py myhost.corp.local
"""
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studio.tls import make_test_certificate  # noqa: E402

hosts = ["localhost", "127.0.0.1", socket.gethostname()] + sys.argv[1:]
cert, key = ROOT / "certs" / "test-cert.pem", ROOT / "certs" / "test-key.pem"
make_test_certificate(cert, key, hosts=tuple(dict.fromkeys(hosts)))
print("TEST certificate written (valid 90 days) for: " + ", ".join(dict.fromkeys(hosts)))
print("  " + str(cert))
print("  " + str(key))
print('For a test run set: "tls_enabled": true, "tls_cert_file": "certs/test-cert.pem", '
      '"tls_key_file": "certs/test-key.pem", "tls_allow_self_signed": true')
