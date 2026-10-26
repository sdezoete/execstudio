# Deploying on the air-gapped server

Short version of the install. The [README](README.md) has the full detail on HTTPS and certificates.

## 1. What the server needs

- Windows Server, 64-bit, with **Python 3.11 (x64)**. The Python installer is not in this package: bring `python-3.11.x-amd64.exe` on the same media.
- The **9 wheels** in `wheels\`. They are built for Windows x64 / Python 3.11, and together they are the complete set (checked by installing into an empty environment with no internet: `pip check` clean, all tests pass).

| Wheel | Needed for |
|---|---|
| `python_pptx-1.0.2` | templates, native charts, editing uploaded decks |
| `lxml-6.1.3`, `pillow-13.0.0`, `xlsxwriter-3.3.0`, `typing_extensions-4.16.0` | required by python-pptx |
| `pypdf-5.9.0` | reading PDF uploads |
| `cryptography-46.0.7` | HTTPS with a `.pfx` certificate |
| `cffi-2.1.1`, `pycparser-3.11` | required by cryptography |

Nothing else is needed: the server, the LLM client and the Word, Excel and CSV readers use only the Python standard library.

## 2. What to copy

Copy the whole `exec-studio` folder, **including `wheels\`**. `wheels\`, `.env`, `certs\` and `config.json` are not in git, so copy from a working folder, or run `scripts\1-download-wheels.ps1` on a machine with internet first.

Leave out `.venv\`, `logs\`, `work\` and `__pycache__\`. In `.env`, **delete the `OPENAI_API_KEY` line** before copying: it is a development key and must not go to the server.

## 3. Install (on the server)

```powershell
cd D:\Apps\exec-studio
powershell -ExecutionPolicy Bypass -File scripts\2-install-offline.ps1
```

The script creates `.venv`, installs from `wheels\` without internet access, creates `config.json` and finishes with a check line. It should read:

```
PowerPoint engine: python-pptx 1.0.2 | PDF reading: True | .pfx certificates: True
```

## 4. Connect the local LLM

The studio works with any **OpenAI-compatible** chat-completions endpoint (DeepSeek, vLLM, SGLang, LiteLLM, the corporate MaaS gateway). Set it in `.env` next to `server.py`:

```ini
DEVELOPMENT=False
LLM_BASE_URL=https://<llm-host>:<port>/v1
LLM_API_KEY=<key issued for this app; leave empty if the endpoint needs none>
LLM_MODEL=<exact model id>
LLM_VERIFY_SSL=True
LLM_TIMEOUT_SECONDS=120
LLM_MAX_TOKENS=4096
```

- **`DEVELOPMENT=False`** is the switch to the local model. With it, the `LLM_*` values above override anything in `config.json`. If you would rather not use `.env`, leave `LLM_*` out and set `llm_base_url`, `llm_api_key` and `llm_model` in `config.json` instead.
- **`LLM_BASE_URL`** ends in `/v1`. The studio calls `<base>/chat/completions` and checks reachability with `<base>/models`.
- **`LLM_MODEL`** must match the server's id exactly. List the ids with:
  `Invoke-RestMethod https://<llm-host>:<port>/v1/models -Headers @{Authorization="Bearer <key>"}`
- **Internal certificate:** if the LLM endpoint uses a certificate from an internal CA that Windows does not trust, set `"llm_ca_file": "certs/internal-ca.pem"` in `config.json`. Use `LLM_VERIFY_SSL=False` only as a temporary test.
- **Proxy:** proxy environment variables are ignored for LLM calls by default (`"llm_ignore_proxy": true`). That suits an endpoint on the internal network.
- **JSON mode:** the studio asks for JSON output. If the endpoint rejects `response_format`, the studio drops it and retries automatically. Set `"llm_json_mode": false` only if you see repeated errors.

## 5. HTTPS, start and autostart

1. **Certificate:** from an Administrator PowerShell, run `scripts\export-cert-from-store.ps1`. It writes `certs\server.pfx`, which `config.json` already points to. See the README's HTTPS section for PEM files.
2. **Start:** run `scripts\run-server.bat`, then open `https://<server name on the certificate>:8443`.
3. **Autostart:** from an Administrator PowerShell, run `scripts\install-startup-task.ps1`. It runs the studio at boot, restarts it if it stops, and opens the port in the firewall.

## 6. Check it works

- **Console:** the startup output must show `LLM <model> at <url>: reachable`. In the browser, the top-right pill shows a green dot, and `https://<server>:8443/api/health` reports `"reachable": true`.
- **If it says unreachable:** the detail in `/api/health` names the cause: wrong URL, refused connection, certificate, or a 401 (wrong key). Without the LLM the studio still runs on built-in rules and labels its output as such.
- **Smoke test:** work through [examples/README.md](examples/README.md). It takes about 15 minutes. Start with the demo there: it uses the files in `use_case_examples\` (a PDF study and a demo-company workbook) and exercises upload, generation, quality check, board assessment and export in one go. Copy `examples\` and `use_case_examples\` with the rest of the folder.
