# Deployment notes per release

Read this before you install an update on the air-gapped server. `scripts\make-usb.ps1` copies it next to the `exec-studio` folder in every `usb_<version>` release.

**The release package contains no server settings.** It has no `.env` and no `config.json`: the server keeps its own. If a release needs a setting added or changed in either file, the change is listed below under that version. Make the change by hand on the server.

**How to use it:**

1. On the server, read `D:\exec-studio\VERSION.txt` to see which version runs now.
2. Install the update as in [DEPLOY.md](DEPLOY.md) §7.
3. Before you start the studio again, apply the **Server settings** of every version below that is newer than the old one, oldest first.

The full list of settings is in `.env.example` and `config.example.json` in the package. They are templates for reference and are never read by the studio.

---

## 1.6.0

**Server settings:** none.

**Packaging, from this version on:** the release no longer contains a `.env`. Earlier releases brought one, which had to be replaced by the server's own. Keep copying `.env` and `config.json` from `exec-studio-prev` as in DEPLOY.md §7: without them the studio would start with the defaults.

**What changed:** uploading a company template as it is. The studio finds the guidance in it, cleans it into a template and follows its directions. USB release folders are now named `usb_<version>`.

## 1.5.3

**Server settings:**

- `config.json`: HTTPS now uses the server's PEM files. Set `"tls_cert_file": "D:/ssl_certificate/certificate.crt"` and `"tls_key_file": "D:/ssl_certificate/privatekey.pem"`, and empty `"tls_pfx_file"` and `"tls_pfx_password_file"`. Skip this if the server still uses a `.pfx` certificate. The account that runs the studio (SYSTEM, for the startup task) needs read access to `D:\ssl_certificate`.

**What changed:** templates without a notes placeholder get one added instead of failing.

## 1.5.2

**Server settings:** none. This was the first release packaged with `make-usb.ps1`.
