"""Settings for the studio.

Values come from, in increasing priority:
  1. DEFAULTS below
  2. config.json next to server.py (or the file named in STUDIO_CONFIG)
  3. environment variables STUDIO_<KEY>, e.g. STUDIO_LLM_BASE_URL

Dev convenience only: if nothing above has pointed llm_base_url anywhere, and a
.env file (or the real environment) sets OPENAI_API_KEY, the studio talks to
the real OpenAI API instead of localhost. This never applies once llm_base_url
is actually configured, so it cannot redirect a production DeepSeek setup.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "host": "0.0.0.0",
    "port": 8080,
    # HTTPS. On the server use your organisation's certificate (a .pfx, or PEM cert + key).
    "tls_enabled": False,
    "tls_pfx_file": "",             # e.g. "certs/server.pfx"
    "tls_pfx_password": "",         # or put it in a protected file and use tls_pfx_password_file
    "tls_pfx_password_file": "",
    "tls_cert_file": "",            # PEM alternative: certificate + intermediate chain
    "tls_key_file": "",
    "tls_key_password": "",
    "tls_key_password_file": "",
    "tls_min_version": "1.2",
    "tls_allow_self_signed": False, # test machines only
    "http_redirect_port": 0,        # e.g. 80: plain-HTTP listener that redirects to HTTPS; 0 = off
    # Any OpenAI-compatible chat-completions endpoint. DeepSeek's own server and
    # common gateways (vLLM, SGLang, LiteLLM, Ollama's /v1) all qualify.
    "llm_enabled": True,
    "llm_base_url": "http://localhost:8000/v1",
    "llm_api_key": "",
    "llm_model": "deepseek-4.1-flash",
    "llm_display_name": "DeepSeek 4.1 Flash",
    "llm_timeout": 120,
    "llm_temperature": 0.3,
    "llm_max_tokens": 4096,
    "llm_json_mode": True,          # send response_format={"type":"json_object"}
    "llm_ignore_proxy": True,       # ignore HTTP(S)_PROXY env vars for the LLM call
    "llm_ca_file": "",              # extra CA (PEM) if DeepSeek uses HTTPS with an internal CA not in the Windows store
    "max_upload_mb": 20,
    "max_context_chars": 40000,     # text from uploads/facts sent to the model
    "audit_log": "logs/audit.log",  # metadata only, never slide content
    "server_log": "logs/server.log",
    "work_dir": "work",             # uploaded decks and generated files, auto-deleted
    "work_retention_hours": 24,
}


def _coerce(raw, default):
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


def _load_dotenv():
    """Load KEY=VALUE lines from .env next to server.py into os.environ. Dev convenience
    only; no effect if absent. Deliberately overrides any same-named ambient/machine
    environment variable, so a stale system-wide OPENAI_API_KEY can't shadow this project's
    own .env (that collision is exactly what this is for)."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


def load():
    _load_dotenv()
    cfg = dict(DEFAULTS)
    path = Path(os.environ.get("STUDIO_CONFIG", ROOT / "config.json"))
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    for key, default in DEFAULTS.items():
        raw = os.environ.get("STUDIO_" + key.upper())
        if raw is not None:
            cfg[key] = _coerce(raw, default)

    if cfg["llm_base_url"] == DEFAULTS["llm_base_url"] and os.environ.get("OPENAI_API_KEY"):
        cfg["llm_base_url"] = "https://api.openai.com/v1"
        cfg["llm_api_key"] = os.environ["OPENAI_API_KEY"]
        cfg["llm_model"] = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
        cfg["llm_display_name"] = cfg["llm_model"] + " (OpenAI, dev placeholder for DeepSeek)"
    return cfg
