"""HTTPS for the studio, using Python's built-in ssl module.

Certificates can be given as
  * a PFX / P12 file (what Windows exports from the certificate store), or
  * PEM files: certificate (with intermediate chain) + private key.

PFX files are read with the `cryptography` library (shipped in wheels\\). The key
is handed to the ssl module through a temporary file that is itself encrypted
with a random one-time password and deleted straight away.

Safety rules enforced here:
  * self-signed certificates are refused unless tls_allow_self_signed is true
    (for test machines only);
  * expired certificates are refused;
  * TLS 1.2 is the minimum.
"""
import datetime as _dt
import os
import secrets
import shutil
import ssl
import tempfile
from pathlib import Path

from .config import ROOT

try:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, Encoding, PrivateFormat, pkcs12
    HAVE_CRYPTOGRAPHY = True
except BaseException as _e:  # optional dependency; a broken install must not stop the server
    if isinstance(_e, (KeyboardInterrupt, SystemExit)):
        raise
    HAVE_CRYPTOGRAPHY = False


class TLSConfigError(Exception):
    pass


def _path(p):
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def _secret(cfg, key):
    """A password from config, or from a file named by <key>_file (useful for a Windows service account)."""
    value = cfg.get(key) or ""
    file_key = key + "_file"
    if not value and cfg.get(file_key):
        f = _path(cfg[file_key])
        if not f.exists():
            raise TLSConfigError("The password file %s does not exist." % f)
        value = f.read_text(encoding="utf-8-sig").strip()
    return value


def build_context(cfg):
    """Return (ssl.SSLContext, info dict). Raises TLSConfigError with a clear message on any problem."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3 if str(cfg.get("tls_min_version")) == "1.3" else ssl.TLSVersion.TLSv1_2

    if cfg.get("tls_pfx_file"):
        info = _load_pfx(ctx, _path(cfg["tls_pfx_file"]), _secret(cfg, "tls_pfx_password"))
    elif cfg.get("tls_cert_file") and cfg.get("tls_key_file"):
        cert, key = _path(cfg["tls_cert_file"]), _path(cfg["tls_key_file"])
        for f, what in ((cert, "certificate"), (key, "private key")):
            if not f.exists():
                raise TLSConfigError("The %s file %s does not exist." % (what, f))
        try:
            ctx.load_cert_chain(str(cert), str(key), password=_secret(cfg, "tls_key_password") or None)
        except ssl.SSLError as e:
            raise TLSConfigError("The certificate and private key could not be loaded: they may not match, "
                                 "or the key password is wrong (%s)." % e.reason) from e
        info = _describe_pem(cert)
    else:
        raise TLSConfigError("HTTPS is on (tls_enabled) but no certificate is set. Set tls_pfx_file, "
                             "or tls_cert_file and tls_key_file, in config.json.")

    now = _dt.datetime.now(_dt.timezone.utc)
    if info.get("not_after") and info["not_after"] < now:
        raise TLSConfigError("The certificate expired on %s. Install a renewed certificate." % info["not_after"].date())
    if info.get("self_signed") and not cfg.get("tls_allow_self_signed"):
        raise TLSConfigError("The certificate is self-signed. Self-signed certificates are only for testing: "
                             "use your organisation's certificate on the server, or set "
                             "tls_allow_self_signed to true on a test machine.")
    if info.get("not_after"):
        info["days_left"] = (info["not_after"] - now).days
    return ctx, info


def _load_pfx(ctx, path, password):
    if not path.exists():
        raise TLSConfigError("The certificate file %s does not exist." % path)
    if not HAVE_CRYPTOGRAPHY:
        raise TLSConfigError("Reading .pfx files needs the 'cryptography' library (in wheels\\). Run "
                             "scripts\\2-install-offline.ps1, or use PEM files (tls_cert_file + tls_key_file).")
    try:
        key, cert, extra = pkcs12.load_key_and_certificates(path.read_bytes(), password.encode("utf-8") if password else None)
    except ValueError as e:
        raise TLSConfigError("The .pfx file could not be opened: the password is wrong or the file is damaged.") from e
    if key is None or cert is None:
        raise TLSConfigError("The .pfx file has no private key. Export it again with the private key included.")

    one_time = secrets.token_urlsafe(24)
    tmp = Path(tempfile.mkdtemp(prefix="studio-tls-"))
    try:
        cert_file, key_file = tmp / "chain.pem", tmp / "key.pem"
        cert_file.write_bytes(cert.public_bytes(Encoding.PEM) + b"".join(c.public_bytes(Encoding.PEM) for c in (extra or [])))
        key_file.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(one_time.encode())))
        ctx.load_cert_chain(str(cert_file), str(key_file), password=one_time)
    except ssl.SSLError as e:
        raise TLSConfigError("The certificate in the .pfx file could not be used (%s)." % e.reason) from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    info = _describe_x509(cert)
    info["chain"] = len(extra or [])
    info["source"] = str(path)
    return info


def _describe_x509(cert):
    def cn(name):
        attrs = name.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        return attrs[0].value if attrs else name.rfc4514_string()
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = [str(v) for v in san.get_values_for_type(x509.DNSName)] + \
                [str(v) for v in san.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        names = []
    not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=_dt.timezone.utc)
    return {"subject": cn(cert.subject), "issuer": cn(cert.issuer), "names": names,
            "not_after": not_after, "self_signed": cert.issuer == cert.subject}


def _describe_pem(path):
    if HAVE_CRYPTOGRAPHY:
        try:
            info = _describe_x509(x509.load_pem_x509_certificate(path.read_bytes()))
            info["source"] = str(path)
            return info
        except Exception:  # noqa: BLE001  (fall through to the ssl module's decoder)
            pass
    try:
        d = ssl._ssl._test_decode_cert(str(path))  # noqa: SLF001  (stdlib, undocumented but stable)
    except Exception:  # noqa: BLE001
        return {"source": str(path)}

    def flat(rdns):
        return {k: v for rdn in rdns for k, v in rdn}
    subj, iss = flat(d.get("subject", ())), flat(d.get("issuer", ()))
    not_after = _dt.datetime.strptime(d["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=_dt.timezone.utc) if d.get("notAfter") else None
    return {"subject": subj.get("commonName", ""), "issuer": iss.get("commonName", ""),
            "names": [v for _, v in d.get("subjectAltName", ())], "not_after": not_after,
            "self_signed": d.get("subject") == d.get("issuer"), "source": str(path)}


def client_context(ca_file="", verify=True):
    """SSL context for outgoing calls to the LLM endpoint (DeepSeek direct, or the corporate MaaS
    gateway). Uses the Windows trust store plus an optional CA file, or disables verification
    entirely when the gateway's certificate can't be validated normally -- this is LLM_VERIFY_SSL
    in the Central LLM Client guide, which recommends 'false' for the corporate MaaS endpoint."""
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if ca_file:
        p = _path(ca_file)
        if not p.exists():
            raise TLSConfigError("llm_ca_file %s does not exist." % p)
        ctx.load_verify_locations(cafile=str(p))
    return ctx


def make_test_certificate(cert_path, key_path, hosts=("localhost", "127.0.0.1"), days=90):
    """Self-signed certificate for TESTING ONLY (development PCs, automated tests)."""
    if not HAVE_CRYPTOGRAPHY:
        raise TLSConfigError("Creating a test certificate needs the 'cryptography' library.")
    import ipaddress
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import NoEncryption
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Executive Presentation Studio TEST"),
                      x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, "TEST ONLY - not for production")])
    alt = []
    for h in hosts:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            alt.append(x509.DNSName(h))
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - _dt.timedelta(minutes=5))
            .not_valid_after(now + _dt.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    Path(cert_path).parent.mkdir(parents=True, exist_ok=True)
    Path(cert_path).write_bytes(cert.public_bytes(Encoding.PEM))
    Path(key_path).write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
