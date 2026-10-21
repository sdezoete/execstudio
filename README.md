# Executive Presentation Studio

A stand-alone web app that helps people build executive-level presentations. It can:

- draft an answer-first storyline
- recommend slide layouts
- check quality
- prepare people for likely questions
- export an editable PowerPoint file
- improve existing PowerPoint decks

It runs on an **air-gapped Windows Server** with **Python 3.11**, serves **HTTPS with your organisation's certificate**, and uses the on-premise **DeepSeek** model.

- **Server:** Python standard library (`http.server`), so there is no web framework to install.
- **Optional libraries** (shipped in `wheels\`):
  - **python-pptx** enables corporate templates, native charts and editing existing decks.
  - **pypdf** enables reading PDF uploads.
  - **cryptography** enables loading `.pfx` certificate files for HTTPS.
- **Frontend:** plain HTML, CSS and JavaScript. No frameworks, CDNs or web fonts; the browser only talks to this server.

---

## Install on the Windows server

The package already contains the Windows wheels for Python 3.11 in `wheels\`, so no internet access is needed.

1. Copy the `exec-studio` folder to the server, for example to `D:\Apps\exec-studio`.
2. Open PowerShell in that folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\2-install-offline.ps1
   ```
   This does four things:
   - finds Python 3.11
   - creates `.venv`
   - installs the libraries from `wheels\`
   - creates `config.json`
3. Edit `config.json` and set the DeepSeek endpoint:
   ```json
   "llm_base_url": "http://<deepseek-host>:<port>/v1",
   "llm_model": "<model name your server expects>"
   ```
   To get the exact model name, run this on the server:
   `Invoke-RestMethod http://<deepseek-host>:<port>/v1/models`
4. **Set up HTTPS with your certificate.** See [HTTPS](#https) below. In short, from an Administrator PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\export-cert-from-store.ps1
   ```
5. Start it:
   ```bat
   scripts\run-server.bat
   ```
   Then open `https://<server name on the certificate>:8443`. The console prints:
   - the certificate in use and its expiry date
   - whether DeepSeek is reachable
   - which features are active
6. To run it automatically at boot, run this from an **Administrator** PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install-startup-task.ps1
   ```
   This registers a Windows Scheduled Task that runs under the SYSTEM account and restarts the server if it stops. It also opens the port from `config.json` in Windows Firewall, for the Domain and Private profiles. To undo both, run the same script with `-Remove`.

---

## HTTPS

The production server serves **HTTPS only, with your organisation's certificate**. Self-signed certificates are for testing on development PCs, and the server **refuses to start** with one unless `tls_allow_self_signed` is `true`. Keep that setting `false` on the server.

### On the server: use your certificate

**Option A: the certificate is already in the Windows certificate store.** This is the usual case when IT has issued it to the server. From an Administrator PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\export-cert-from-store.ps1                 # lists candidates
powershell -ExecutionPolicy Bypass -File scripts\export-cert-from-store.ps1 -Thumbprint <thumbprint>
```

The script:
- exports the certificate, its private key and the intermediate chain to `certs\server.pfx`
- saves the password you choose in `certs\pfx-password.txt`
- restricts the `certs` folder to Administrators and SYSTEM
- prints the lines for `config.json`

If the key is marked *not exportable*, ask IT for the .pfx file instead.

**Option B: IT gives you a .pfx/.p12 file.** Copy it to `certs\server.pfx`, put its password in `certs\pfx-password.txt`, and restrict the folder:
`icacls certs /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F`

**Option C: IT gives you PEM files.** Use the certificate (with intermediates appended) and its key:
```json
"tls_pfx_file": "",
"tls_cert_file": "certs/server-chain.pem",
"tls_key_file": "certs/server.key",
"tls_key_password_file": "certs/key-password.txt"
```

A typical `config.json` for options A and B:
```json
"port": 8443,
"tls_enabled": true,
"tls_pfx_file": "certs/server.pfx",
"tls_pfx_password_file": "certs/pfx-password.txt",
"tls_allow_self_signed": false,
"tls_min_version": "1.2",
"http_redirect_port": 0
```

**Notes:**
- **Ports.** To use the standard port, set `"port": 443`, provided nothing else on the server (for example IIS) is using it. To catch users who type `http://`, set `"http_redirect_port": 80`; that listener only redirects to HTTPS.
- **Names.** Users must open the studio by a name on the certificate. The startup log lists the valid names.
- **Expiry.** The log warns when the certificate has fewer than 30 days left, and an expired certificate is refused. To renew, replace `certs\server.pfx`, then restart the task:
  `Stop-ScheduledTask ExecutivePresentationStudio; Start-ScheduledTask ExecutivePresentationStudio`.
- **What HTTPS enforces.** Connections use TLS 1.2 or newer; set `tls_min_version` to `"1.3"` to require TLS 1.3. Responses carry `Strict-Transport-Security`.
- **Handshake protection.** Each connection completes its handshake in its own thread, so a slow or broken client cannot block other users.
- **If DeepSeek is also served over HTTPS:** an internal CA that is installed in the Windows certificate store is trusted automatically. Otherwise, point `llm_ca_file` at the CA's PEM file.

### For testing only: a self-signed certificate

On a development PC:

```bat
.venv\Scripts\python scripts\make-test-cert.py
```

This writes `certs\test-cert.pem` and `certs\test-key.pem`, valid for 90 days for localhost and the PC's name. In VS Code, run **Studio over HTTPS (self-signed TEST certificate)**; it creates the certificate and allows it for that run only. The browser will warn about the certificate, which is expected for a self-signed test certificate.

### Updating the libraries later

On a laptop **with** internet access, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\1-download-wheels.ps1
```

This refreshes `wheels\` with Windows and Python 3.11 builds, even if the laptop runs a different operating system. Copy the folder to the server and run step 2 again.

If the server turns out to be ARM-based rather than x64, change `win_amd64` in that script to `win_arm64`.

---

## Working in VS Code

Open the `exec-studio` folder in VS Code. The project includes ready-made settings in `.vscode/`.

- **Development runs.** The development launch configurations run plain HTTP on port 8080. The HTTPS configuration uses a throwaway test certificate, so you don't need the production certificate on a laptop.
- **Interpreter.** The project is preset to `.venv\Scripts\python.exe`. If VS Code asks, choose that interpreter.
- **Run and Debug (F5):**
  - **Studio server** runs the app with the debugger attached, using `config.json`.
  - **Studio + mock AI** starts a fake DeepSeek on port 8001 first. Use it to develop without the real model.
  - **Tests** runs the test suite under the debugger.
- **Terminal → Run Task:**
  - **Run studio server**
  - **Run tests**
  - **Install libraries offline**
  - **Make sample deck**, which writes `tests\sample.pptx` with a chart, picture and table for trying out deck transformation
- **Testing panel.** Tests are discovered automatically (unittest).

Recommended extensions are **Python** and **Python Debugger**, both from Microsoft. If VS Code has no Marketplace access, download the `.vsix` files on a laptop and install them with *Extensions → … → Install from VSIX*.

---

## What it does with PowerPoint

### Creating decks

**Export** produces an editable .pptx with:

- the headline in each slide's real title placeholder
- native shapes for scorecards, driver trees, matrices, roadmaps and risk maps
- **native, editable charts** whenever numbers are available, either because the AI found them in uploaded data or because the user entered them in a slide's *Chart data* box
- speaker notes in every slide

### Using your corporate templates

1. Put your `.potx` or `.pptx` files in `data\templates\`.
2. Register each one in `data\templates.json`. `data\templates\README.txt` explains every field.

Slides are then built on your real masters and layouts. Until the files are in place, the app uses a clean built-in 16:9 template.

### Improving an existing deck

Choose *Improve an existing deck* and upload a .pptx. The app lists every slide with its charts, tables and pictures. Select slides, then choose any of three changes:

- **Rewrite headlines as action titles.** The AI rewrites the titles and keeps every fact.
- **Simplify the main text.** Each slide is cut to at most five points, and every number is kept.
- **Move onto the corporate template.** The selected slides are rebuilt on the approved template.
  - Charts are rebuilt as native charts in template colours.
  - Tables and pictures are carried over.
  - SmartArt, grouped diagrams and media can't be carried over; the change report lists them so they can be copied manually.

Without *Move onto the corporate template*, the edits are made **in place**: all slides are kept and the original formatting is preserved. A change report shows each slide's headline before and after, plus any warnings.

You can also select **Restructure my presentation** instead. This builds a new answer-first storyline from the uploaded deck's content.

---

## Configuration (`config.json`)

| Setting | Meaning |
|---|---|
| `host`, `port` | Where the server listens. The example config uses `0.0.0.0:8443`. |
| `tls_enabled` | Serve HTTPS. Must be `true` on the server. |
| `tls_pfx_file`, `tls_pfx_password_file` | Your certificate as .pfx, plus a protected file holding its password (or `tls_pfx_password`). |
| `tls_cert_file`, `tls_key_file`, `tls_key_password_file` | PEM alternative to the .pfx settings. |
| `tls_allow_self_signed` | `false` on the server. `true` only on test machines. |
| `tls_min_version` | `"1.2"` (default) or `"1.3"`. |
| `http_redirect_port` | Optional plain-HTTP port that redirects to HTTPS. `0` turns it off. |
| `llm_ca_file` | Extra CA file if DeepSeek uses HTTPS with an internal CA that isn't in the Windows store. |
| `llm_base_url` | DeepSeek's OpenAI-compatible endpoint, ending in `/v1`. |
| `llm_model`, `llm_display_name` | The model name sent to the API, and the name shown to users. |
| `llm_api_key` | Bearer token, if your gateway needs one. |
| `llm_json_mode` | Asks for JSON replies. The app retries without this if the server rejects it. |
| `llm_ignore_proxy` | Ignores proxy environment variables for the model call. |
| `max_upload_mb`, `max_context_chars` | Upload size limit, and how much text is sent to the model. |
| `work_dir`, `work_retention_hours` | Temporary storage for uploaded decks and results. Files are deleted after 24 hours by default. |
| `audit_log`, `server_log` | Log files under `logs\`. |

Every setting can be overridden with an environment variable, for example `set STUDIO_PORT=9000`.

If DeepSeek is unreachable, every AI feature falls back to built-in rules. The interface labels that output clearly.

---

## Governance

- **No invented numbers.** The prompts tell the model to use only figures the user supplies; anything missing becomes a `[placeholder]`. The quality check flags placeholders, and the slide footer marks missing evidence.
- **Charts only from real data.** The AI may add a chart only when the numbers are in the provided material.
- **Uploaded files and slide text are treated as data, not instructions.** This guards against prompt injection hidden in documents.
- **Audit log.** `logs\audit.log` records each action as JSON lines. It holds metadata only (time, action, template, AI or rules, duration) and never content.
- **Short-lived uploads.** Uploaded decks are kept in `work\` under random ids and deleted automatically.
- **HTTPS only in production.** The server uses your organisation's certificate, refuses self-signed and expired certificates, requires TLS 1.2 or newer, and sends HSTS. The certificate and its password sit in `certs\`, which only Administrators and SYSTEM can read.
- **Browser security.** A strict Content-Security-Policy is set and every asset is served from this server.

## Known limits

- **There is no login.** Put the app behind your reverse proxy or single sign-on, or restrict access with the firewall rule, before wider rollout.
- **SmartArt and grouped diagrams** are not rebuilt when moving slides onto the template; they are listed in the change report.
- **Scanned PDFs have no text layer** and can't be read. Upload the original document instead.
- **Legacy formats are rejected.** `.ppt`, `.doc` and `.xls` files must first be saved in the newer formats (`.pptx`, `.docx`, `.xlsx`).

## Project layout

```
server.py                 web server: static files + /api
config.example.json       copy to config.json
requirements.txt          optional libraries (python-pptx, pypdf)
wheels\                   Windows / Python 3.11 wheels for offline install
scripts\                  1-download-wheels.ps1, 2-install-offline.ps1, export-cert-from-store.ps1,
                          run-server.bat, install-startup-task.ps1, make-test-cert.py (testing only)
certs\                    your certificate (created at install; not shipped)
studio\
  services.py             endpoint logic; tries the LLM, falls back to rules; audit log
  llm.py, prompts.py      DeepSeek client and prompts
  fallback.py, review.py  built-in rules and quality checks
  schema.py               validation of browser and LLM data
  extract.py              text from .pptx/.docx/.xlsx/.pdf/.csv/.txt/.md
  workspace.py            temporary file storage
  tls.py                  HTTPS: certificate loading (.pfx or PEM), safety rules, test certificates
  slides\
    layouts.py            slide layouts, written once for both engines
    pptx_engine.py        python-pptx engine (templates, native charts)
    xml_engine.py         standard-library fallback engine
    deck.py               inventory, in-place edits, re-templating of existing decks
data\                     templates.json, templates\, repository.json, toolkit.json
static\                   index.html, css\app.css, js\api.js, js\thumbs.js, js\app.js
tests\                    API tests, mock DeepSeek, sample deck builder
.vscode\                  launch, tasks, settings, recommended extensions
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status of DeepSeek, the PowerPoint engine and PDF reading |
| GET | `/api/meta`, `/api/repository`, `/api/toolkit` | Reference data |
| POST | `/api/storyline` | `{brief, version, context}` → `{title, slides[], source}` |
| POST | `/api/review`, `/api/qa`, `/api/advise`, `/api/sharpen` | Quality check, Q&A prep, slide advisor, headline rewrite |
| POST | `/api/extract` | Raw file body plus an `X-Filename` header → extracted text |
| POST | `/api/export/pptx`, `/api/export/briefing` | PowerPoint download; Markdown briefing pack |
| POST | `/api/deck/upload` | Raw .pptx body → `{deck_id, slides[], text}` |
| POST | `/api/deck/transform` | `{deck_id, selected[], actions{headlines, simplify, retemplate}, brief}` → `{file_id, report[]}` |
| GET | `/api/download/<file_id>` | Fetch a generated file |
