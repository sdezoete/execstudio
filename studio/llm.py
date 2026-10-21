"""Client for the configured LLM endpoint over an OpenAI-compatible API: the real
endpoint is either OpenAI (DEVELOPMENT=True, see config.py) or the corporate Aramco
MaaS gateway running DeepSeek V4.1 Flash (DEVELOPMENT=False) -- both speak the same
chat-completions wire contract, so one client handles either without changes here.

Standard library only. Every public call raises LLMError on any failure so the
API layer can fall back to built-in rules instead of failing the user.
"""
import json
import re
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_json(text):
    """Pull a JSON object out of a model reply (tolerates reasoning tags and code fences)."""
    if not text:
        raise LLMError("The model returned an empty reply.")
    t = _THINK.sub("", text).strip()
    t = _FENCE.sub("", t).strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except ValueError:
            pass
    raise LLMError("The model reply was not valid JSON.")


class LLMClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg["llm_base_url"].rstrip("/")
        handlers = [urllib.request.ProxyHandler({})] if cfg.get("llm_ignore_proxy", True) else []
        if self.base.startswith("https://"):
            from .tls import client_context
            handlers.append(urllib.request.HTTPSHandler(
                context=client_context(cfg.get("llm_ca_file", ""), cfg.get("llm_verify_ssl", True))))
        self.opener = urllib.request.build_opener(*handlers)
        self._json_mode = bool(cfg.get("llm_json_mode", True))
        self._token_param = "max_tokens"  # some newer models (e.g. OpenAI's gpt-5/o-series) require max_completion_tokens
        self._health = (0.0, None)

    @property
    def enabled(self):
        return bool(self.cfg.get("llm_enabled", True))

    @property
    def model(self):
        return self.cfg["llm_model"]

    @property
    def display_name(self):
        return self.cfg.get("llm_display_name") or self.model

    def _headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.cfg.get("llm_api_key"):
            h["Authorization"] = "Bearer " + self.cfg["llm_api_key"]
        return h

    # Some networks reset or fake-401 a fraction of outbound HTTPS connections (observed
    # against api.openai.com); a short retry absorbs that without masking real failures.
    # 400/422 are deliberately excluded so chat()'s response_format renegotiation still runs.
    _RETRYABLE_HTTP = {401, 403, 408, 429, 500, 502, 503, 504}

    def _post(self, path, body, timeout, attempts=None):
        attempts = int(self.cfg.get("llm_max_retries", 5)) if attempts is None else attempts
        data = json.dumps(body).encode("utf-8")
        for attempt in range(attempts):
            try:
                req = urllib.request.Request(self.base + path, data=data, headers=self._headers(), method="POST")
                with self.opener.open(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code not in self._RETRYABLE_HTTP or attempt == attempts - 1:
                    raise
                time.sleep(1.5)
            except Exception:
                if attempt == attempts - 1:
                    raise
                time.sleep(1.5)

    def chat(self, system, user, json_mode=True, temperature=None, max_tokens=None):
        if not self.enabled:
            raise LLMError("The AI service is switched off in the server settings.")
        use_json = json_mode and self._json_mode
        tokens = max_tokens or self.cfg["llm_max_tokens"]

        def _body():
            b = {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": self.cfg["llm_temperature"] if temperature is None else temperature,
                self._token_param: tokens,
                "stream": False,
            }
            if self.cfg.get("llm_top_p") not in (None, ""):
                b["top_p"] = self.cfg["llm_top_p"]
            if self.cfg.get("llm_top_k") not in (None, ""):
                b["top_k"] = self.cfg["llm_top_k"]
            if self.cfg.get("llm_reasoning_effort"):
                b["reasoning_effort"] = self.cfg["llm_reasoning_effort"]
            if use_json:
                b["response_format"] = {"type": "json_object"}
            return b

        # Up to 3 tries: the request as configured, then at most two one-shot corrections
        # (drop response_format, or swap max_tokens <-> max_completion_tokens) remembered for next time.
        last_err = None
        for _ in range(3):
            try:
                data = self._post("/chat/completions", _body(), self.cfg["llm_timeout"])
                break
            except urllib.error.HTTPError as e:
                detail = _error_text(e)
                if "max_completion_tokens" in detail and self._token_param == "max_tokens":
                    self._token_param = "max_completion_tokens"
                elif use_json and e.code in (400, 422):
                    use_json = self._json_mode = False
                else:
                    raise LLMError(_describe(e)) from e
                last_err = e
            except Exception as e:  # noqa: BLE001
                raise LLMError(_describe(e)) from e
        else:
            raise LLMError(_describe(last_err))
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("Unexpected reply format from the AI service.") from e

    def chat_json(self, system, user, **kw):
        return parse_json(self.chat(system, user, json_mode=True, **kw))

    def health(self, max_age=30):
        """Cheap reachability check, cached for max_age seconds."""
        ts, cached = self._health
        if cached is not None and time.time() - ts < max_age:
            return cached
        if not self.enabled:
            result = {"enabled": False, "reachable": False, "model": self.display_name,
                      "detail": "The AI service is switched off in the server settings."}
        else:
            last_err = None
            attempts = int(self.cfg.get("llm_max_retries", 5))
            for attempt in range(attempts):
                try:
                    req = urllib.request.Request(self.base + "/models", headers=self._headers())
                    with self.opener.open(req, timeout=5):
                        pass
                    last_err = None
                    break
                except urllib.error.HTTPError as e:
                    # The server answered, so it is reachable even if /models isn't exposed.
                    if e.code in (404, 405):
                        last_err = None
                        break
                    last_err = e
                    if attempt < attempts - 1:
                        time.sleep(1.5)
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    if attempt < attempts - 1:
                        time.sleep(1.5)
            result = {"enabled": True, "reachable": last_err is None, "model": self.display_name,
                      "detail": "" if last_err is None else _describe(last_err)}
        self._health = (time.time(), result)
        return result


def _error_text(err):
    try:
        return err.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def _describe(err):
    if isinstance(err, urllib.error.HTTPError):
        if err.code in (401, 403):
            return "The AI service rejected the API key."
        return "The AI service returned HTTP %d." % err.code
    if isinstance(err, urllib.error.URLError):
        return "Cannot reach the AI service (%s)." % getattr(err, "reason", err)
    if isinstance(err, TimeoutError):
        return "The AI service did not answer in time."
    return "AI service error: %s" % err
