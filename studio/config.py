"""Settings for the studio.

Values come from, in increasing priority:
  1. DEFAULTS below
  2. config.json next to server.py (or the file named in STUDIO_CONFIG)
  3. environment variables STUDIO_<KEY>, e.g. STUDIO_LLM_BASE_URL
  4. DEVELOPMENT in .env (see below) -- this always wins for LLM settings

Which LLM backend is used is controlled by one flag, DEVELOPMENT, in .env:

  DEVELOPMENT=True   (this machine, has internet) -- OpenAI stands in for the
                      real model, configured from OPENAI_API_KEY / OPENAI_MODEL.
  DEVELOPMENT=False  (the air-gapped server) -- the corporate Aramco MaaS gateway
                      (DeepSeek V4.1 Flash), configured from the LLM_* variables
                      below, per the Central LLM Client Developer Guide (Oct 2026).
                      MaaS speaks the same OpenAI-compatible chat-completions API
                      OpenAI does, so studio/llm.py needs no changes between them.

This project's .env travels with it (USB copy to the air-gapped server): every
LLM_* key already exists with the guide's recommended values, so going live is
"set DEVELOPMENT=False and fill in LLM_API_KEY" -- nothing else to edit.
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
    # Any OpenAI-compatible chat-completions endpoint. DeepSeek's own server, the
    # corporate MaaS gateway, and common gateways (vLLM, SGLang, LiteLLM, Ollama's
    # /v1) all qualify. See DEVELOPMENT in .env: this is overridden by whichever
    # branch below actually applies, so these are only the pre-.env fallbacks.
    "llm_enabled": True,
    "llm_base_url": "http://localhost:8000/v1",
    "llm_api_key": "",
    "llm_model": "deepseek-v41-flash",   # the tested corporate MaaS model ID
    "llm_display_name": "ARIF",
    "llm_timeout": 120,
    "llm_temperature": 0.3,
    "llm_max_tokens": 4096,
    "llm_top_p": "",                # optional; sent only when non-empty
    "llm_top_k": "",                # optional; sent only when non-empty
    "llm_reasoning_effort": "",     # optional; DeepSeek thinking-mode control, sent only when non-empty
    "llm_max_retries": 5,
    "llm_verify_ssl": True,         # set False for a gateway whose certificate isn't in the trust store
    "llm_json_mode": True,          # send response_format={"type":"json_object"}
    "llm_ignore_proxy": True,       # ignore HTTP(S)_PROXY env vars for the LLM call
    "llm_ca_file": "",              # extra CA (PEM) if the endpoint uses HTTPS with a CA not in the Windows store
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


def _truthy(raw, default=True):
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _opt_num(raw, cast):
    if raw is None or raw.strip() == "":
        return ""
    try:
        return cast(raw)
    except ValueError:
        return ""


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

    if _truthy(os.environ.get("DEVELOPMENT"), default=True):
        # This machine, with internet: OpenAI stands in for the real on-prem model.
        if os.environ.get("OPENAI_API_KEY"):
            cfg["llm_base_url"] = "https://api.openai.com/v1"
            cfg["llm_api_key"] = os.environ["OPENAI_API_KEY"]
            cfg["llm_model"] = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
            cfg["llm_max_retries"] = 8  # this dev network drops a meaningful fraction of outbound connections
    else:
        # The air-gapped server: the corporate Aramco MaaS gateway (DeepSeek V4.1 Flash).
        # Every LLM_* key below is read straight from .env/the environment, per the
        # Central LLM Client Developer Guide -- no code change needed to go live.
        cfg["llm_base_url"] = (os.environ.get("LLM_BASE_URL") or cfg["llm_base_url"]).rstrip("/")
        cfg["llm_api_key"] = os.environ.get("LLM_API_KEY", cfg["llm_api_key"])
        cfg["llm_model"] = os.environ.get("LLM_MODEL") or cfg["llm_model"]
        cfg["llm_verify_ssl"] = _truthy(os.environ.get("LLM_VERIFY_SSL"), default=True)
        if os.environ.get("LLM_TIMEOUT_SECONDS"):
            cfg["llm_timeout"] = _coerce(os.environ["LLM_TIMEOUT_SECONDS"], cfg["llm_timeout"])
        if os.environ.get("LLM_MAX_TOKENS"):
            cfg["llm_max_tokens"] = _coerce(os.environ["LLM_MAX_TOKENS"], cfg["llm_max_tokens"])
        if os.environ.get("LLM_TEMPERATURE"):
            cfg["llm_temperature"] = _coerce(os.environ["LLM_TEMPERATURE"], cfg["llm_temperature"])
        cfg["llm_top_p"] = _opt_num(os.environ.get("LLM_TOP_P"), float)
        cfg["llm_top_k"] = _opt_num(os.environ.get("LLM_TOP_K"), int)
        cfg["llm_reasoning_effort"] = (os.environ.get("LLM_REASONING_EFFORT") or "").strip()
        if os.environ.get("LLM_MAX_RETRIES"):
            cfg["llm_max_retries"] = _coerce(os.environ["LLM_MAX_RETRIES"], cfg["llm_max_retries"])
    cfg["llm_display_name"] = "ARIF"
    return cfg
