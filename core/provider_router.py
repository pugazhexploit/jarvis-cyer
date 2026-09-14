"""
core/provider_router.py — Intelligent AI Provider Auto-Switching

Routes LLM requests between OpenRouter (primary) and Groq (fallback) with:
  • Automatic budget tracking and threshold-based switching
  • Configurable OpenRouter model rotation (round-robin)
  • Error/rate-limit fallback chain: Model A → B → C → Groq
  • Usage logging to config/provider_usage.json

Environment variables:
  OPENROUTER_API_KEY   — OpenRouter API key
  GROQ_API_KEY         — Groq API key
  OPENROUTER_BUDGET    — Budget threshold in USD (default: 1.00)

Never exposes API keys to frontend or logs.
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import requests

# ── Sentence boundary regex (same as llm_client.py) ──────────────────────────
_SENT_END = re.compile(r'(?<=[.!?])\s+|(?<=\n)\s*\n')

# ── Paths ────────────────────────────────────────────────────────────────────

def _get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = _get_base_dir()
CONFIG_DIR       = BASE_DIR / "config"
MODELS_PATH      = CONFIG_DIR / "provider_models.json"
USAGE_PATH       = CONFIG_DIR / "provider_usage.json"
ENV_PATH         = BASE_DIR / ".env"

# ── API endpoints ────────────────────────────────────────────────────────────
OPENROUTER_BASE  = "https://openrouter.ai/api/v1"
GROQ_BASE        = "https://api.groq.com/openai/v1"

# ── Default config ───────────────────────────────────────────────────────────
_DEFAULT_MODELS = {
    "openrouter_models": [
        "meta-llama/llama-3.2-3b-instruct",
        "google/gemma-2-9b-it:free",
        "mistralai/mistral-7b-instruct",
    ],
    "groq_model": "llama-3.2-3b-preview",
    "cost_per_million_tokens": {
        "meta-llama/llama-3.2-3b-instruct": {"prompt": 0.06, "completion": 0.06},
        "google/gemma-2-9b-it:free":         {"prompt": 0.0,  "completion": 0.0},
        "mistralai/mistral-7b-instruct":     {"prompt": 0.06, "completion": 0.06},
    },
}

_DEFAULT_BUDGET = 1.00

_EMPTY_USAGE = {
    "total_spent":          0.0,
    "total_requests":       0,
    "openrouter_requests":  0,
    "groq_requests":        0,
    "last_reset":           None,
    "history":              [],
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_dotenv() -> dict[str, str]:
    """Parse a simple .env file (KEY=VALUE lines). No shell expansion."""
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    except Exception:
        pass
    return env


def _env(key: str, default: str = "") -> str:
    """Read from os.environ first, fall back to .env file."""
    val = os.environ.get(key, "").strip()
    if val:
        return val
    return _load_dotenv().get(key, default)


# ── Provider Router ──────────────────────────────────────────────────────────

class ProviderRouter:
    """
    Intelligent router for OpenRouter (primary) → Groq (fallback).

    Thread-safe: all state mutations are protected by a lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._model_index = 0

        # ── Load API keys from env ───────────────────────────────────────
        self._openrouter_key = _env("OPENROUTER_API_KEY")
        self._groq_key       = _env("GROQ_API_KEY")

        # ── Load budget ──────────────────────────────────────────────────
        try:
            self._budget = float(_env("OPENROUTER_BUDGET", str(_DEFAULT_BUDGET)))
        except (ValueError, TypeError):
            self._budget = _DEFAULT_BUDGET

        # ── Load model config ────────────────────────────────────────────
        self._models_cfg = self._load_models_config()
        self._openrouter_models: list[str] = self._models_cfg.get(
            "openrouter_models", _DEFAULT_MODELS["openrouter_models"]
        )
        self._groq_model: str = self._models_cfg.get(
            "groq_model", _DEFAULT_MODELS["groq_model"]
        )
        self._cost_table: dict = self._models_cfg.get(
            "cost_per_million_tokens", _DEFAULT_MODELS["cost_per_million_tokens"]
        )

        # ── Load usage state ─────────────────────────────────────────────
        self._usage = self._load_usage()

        avail = "YES" if self._is_budget_available() else "NO (using Groq)"
        print(f"[ProviderRouter] Initialized — budget: ${self._budget:.2f}, "
              f"spent: ${self._usage.get('total_spent', 0):.4f}, "
              f"budget available: {avail}")
        if self._openrouter_key:
            print(f"[ProviderRouter] OpenRouter: {len(self._openrouter_models)} models configured")
        else:
            print("[ProviderRouter] OpenRouter: NO API KEY — will use Groq only")
        if self._groq_key:
            print(f"[ProviderRouter] Groq fallback: {self._groq_model}")
        else:
            print("[ProviderRouter] Groq: NO API KEY")

    # ── Config loading ───────────────────────────────────────────────────

    def _load_models_config(self) -> dict:
        try:
            return json.loads(MODELS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return dict(_DEFAULT_MODELS)

    def _load_usage(self) -> dict:
        try:
            data = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
            # Ensure all expected keys exist
            for k, v in _EMPTY_USAGE.items():
                if k not in data:
                    data[k] = v if not isinstance(v, list) else []
            return data
        except Exception:
            return dict(_EMPTY_USAGE)

    def _save_usage(self) -> None:
        """Persist usage to disk. Caller must hold self._lock."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            # Keep history trimmed to last 500 entries to avoid unbounded growth
            if len(self._usage.get("history", [])) > 500:
                self._usage["history"] = self._usage["history"][-500:]
            USAGE_PATH.write_text(
                json.dumps(self._usage, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[ProviderRouter] Failed to save usage: {e}")

    # ── Budget ───────────────────────────────────────────────────────────

    def _is_budget_available(self) -> bool:
        """True if OpenRouter spend is below the configured threshold."""
        return self._usage.get("total_spent", 0.0) < self._budget

    # ── Model rotation ───────────────────────────────────────────────────

    def _next_openrouter_model(self) -> str:
        """Return the next model in round-robin order and advance the pointer."""
        if not self._openrouter_models:
            return ""
        model = self._openrouter_models[self._model_index % len(self._openrouter_models)]
        self._model_index = (self._model_index + 1) % len(self._openrouter_models)
        return model

    def _current_openrouter_model(self) -> str:
        """Return the current model without advancing."""
        if not self._openrouter_models:
            return ""
        return self._openrouter_models[self._model_index % len(self._openrouter_models)]

    # ── Provider selection ───────────────────────────────────────────────

    def _select_provider(self) -> tuple[str, str, str, str]:
        """
        Returns (provider_name, model, api_key, base_url).
        Checks budget first, then key availability.
        """
        if (self._openrouter_key
                and self._is_budget_available()
                and self._openrouter_models):
            model = self._next_openrouter_model()
            return ("openrouter", model, self._openrouter_key, OPENROUTER_BASE)

        if self._groq_key:
            return ("groq", self._groq_model, self._groq_key, GROQ_BASE)

        # Last resort: try OpenRouter even over budget if Groq is unavailable
        if self._openrouter_key and self._openrouter_models:
            model = self._next_openrouter_model()
            return ("openrouter", model, self._openrouter_key, OPENROUTER_BASE)

        raise RuntimeError(
            "[ProviderRouter] No API keys configured. "
            "Set OPENROUTER_API_KEY and/or GROQ_API_KEY in environment or .env file."
        )

    # ── Cost estimation ──────────────────────────────────────────────────

    def _estimate_cost(
        self, model: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """Estimate cost in USD using the configured cost table."""
        costs = self._cost_table.get(model, {"prompt": 0.10, "completion": 0.10})
        prompt_cost     = (prompt_tokens / 1_000_000) * costs.get("prompt", 0.10)
        completion_cost = (completion_tokens / 1_000_000) * costs.get("completion", 0.10)
        return prompt_cost + completion_cost

    # ── Usage recording ──────────────────────────────────────────────────

    def _record_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost: float,
        status: str,
    ) -> None:
        """Record a request to the usage log. Must be called with lock held."""
        self._usage["total_requests"] = self._usage.get("total_requests", 0) + 1

        if provider == "openrouter":
            self._usage["openrouter_requests"] = self._usage.get("openrouter_requests", 0) + 1
            self._usage["total_spent"] = self._usage.get("total_spent", 0.0) + estimated_cost
        else:
            self._usage["groq_requests"] = self._usage.get("groq_requests", 0) + 1

        self._usage.setdefault("history", []).append({
            "timestamp":         datetime.now(timezone.utc).isoformat(),
            "provider":          provider,
            "model":             model,
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost":    round(estimated_cost, 8),
            "status":            status,
        })

        self._save_usage()

    # ── HTTP helpers ─────────────────────────────────────────────────────

    def _build_headers(self, api_key: str, provider: str) -> dict:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/deestudio028-droid/jarvis"
            headers["X-Title"]     = "JARVIS AI Assistant"
        return headers

    def _build_payload(
        self,
        model: str,
        messages: list,
        tools: list | None,
        stream: bool,
        max_tokens: int = 150,
    ) -> dict:
        """Build an OpenAI-compatible chat completion payload."""
        payload: dict = {
            "model":      model,
            "messages":   messages,
            "stream":     stream,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"]       = tools
            payload["tool_choice"] = "auto"
        return payload

    def _parse_response(self, data: dict) -> dict:
        """Parse a non-streaming OpenAI-compatible response into our format."""
        choice = data.get("choices", [{}])[0]
        msg    = choice.get("message", {})

        raw_tc  = msg.get("tool_calls") or []
        tc_list = []
        for t in raw_tc:
            fn = t.get("function", {})
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    pass
            tc_list.append({
                "id":       t.get("id", ""),
                "function": {"name": fn.get("name", ""), "arguments": args},
            })

        return {
            "content":    (msg.get("content") or "").strip(),
            "tool_calls": tc_list,
        }

    def _extract_usage(self, data: dict) -> tuple[int, int]:
        """Extract token counts from response."""
        usage = data.get("usage", {})
        return (
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )

    # ── Non-streaming call ───────────────────────────────────────────────

    def call(
        self,
        messages: list,
        tools: list | None = None,
        timeout: int = 120,
    ) -> dict:
        """
        Non-streaming chat request with automatic fallback.

        Returns: {"content": str, "tool_calls": list}
        """
        with self._lock:
            errors: list[str] = []
            tried_models: set[str] = set()

            # Try all OpenRouter models first (if budget allows)
            if self._openrouter_key and self._is_budget_available():
                for _ in range(len(self._openrouter_models)):
                    provider, model, key, base = self._select_provider()
                    if provider != "openrouter" or model in tried_models:
                        break
                    tried_models.add(model)

                    try:
                        result, p_tok, c_tok = self._do_call(
                            base, key, provider, model, messages, tools, timeout
                        )
                        cost = self._estimate_cost(model, p_tok, c_tok)
                        self._record_usage(provider, model, p_tok, c_tok, cost, "success")
                        return result
                    except Exception as e:
                        err = f"{provider}/{model}: {e}"
                        errors.append(err)
                        print(f"[ProviderRouter] Error — {err}")
                        self._record_usage(provider, model, 0, 0, 0.0, f"error: {e}")

            # Fallback to Groq
            if self._groq_key:
                try:
                    result, p_tok, c_tok = self._do_call(
                        GROQ_BASE, self._groq_key, "groq",
                        self._groq_model, messages, tools, timeout
                    )
                    self._record_usage("groq", self._groq_model, p_tok, c_tok, 0.0, "success")
                    return result
                except Exception as e:
                    err = f"groq/{self._groq_model}: {e}"
                    errors.append(err)
                    print(f"[ProviderRouter] Groq fallback error — {err}")
                    self._record_usage("groq", self._groq_model, 0, 0, 0.0, f"error: {e}")

            raise RuntimeError(
                f"[ProviderRouter] All providers failed.\n" +
                "\n".join(f"  • {e}" for e in errors)
            )

    def _do_call(
        self,
        base_url: str,
        api_key: str,
        provider: str,
        model: str,
        messages: list,
        tools: list | None,
        timeout: int,
    ) -> tuple[dict, int, int]:
        """Execute a single non-streaming call. Returns (result, prompt_tok, compl_tok)."""
        endpoint = f"{base_url}/chat/completions"
        headers  = self._build_headers(api_key, provider)
        payload  = self._build_payload(model, messages, tools, stream=False)

        resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        p_tok, c_tok = self._extract_usage(data)
        result = self._parse_response(data)
        return result, p_tok, c_tok

    # ── Streaming call ───────────────────────────────────────────────────

    def call_stream(
        self,
        messages: list,
        tools: list | None = None,
        timeout: int = 120,
    ) -> Generator[dict, None, None]:
        """
        Streaming chat request with automatic fallback.

        Yields:
            {"type": "sentence", "text": str}
            {"type": "done", "content": str, "tool_calls": list}
        """
        with self._lock:
            provider, model, key, base = self._select_provider()
            tried: list[tuple[str, str, str, str]] = [(provider, model, key, base)]

        # Try the selected provider first, then fallback
        for attempt, (prov, mdl, k, b) in enumerate(self._fallback_chain(tried)):
            try:
                yield from self._do_stream(b, k, prov, mdl, messages, tools, timeout)
                return
            except Exception as e:
                print(f"[ProviderRouter] Stream error ({prov}/{mdl}): {e}")
                with self._lock:
                    self._record_usage(prov, mdl, 0, 0, 0.0, f"error: {e}")
                # Continue to next fallback

        raise RuntimeError("[ProviderRouter] All streaming providers failed.")

    def _fallback_chain(
        self, tried: list[tuple[str, str, str, str]]
    ) -> Generator[tuple[str, str, str, str], None, None]:
        """Yield provider tuples: first the initial selection, then fallbacks."""
        yield tried[0]

        tried_models = {tried[0][1]}

        # Try remaining OpenRouter models
        with self._lock:
            if self._openrouter_key and self._is_budget_available():
                for _ in range(len(self._openrouter_models)):
                    model = self._next_openrouter_model()
                    if model not in tried_models:
                        tried_models.add(model)
                        yield ("openrouter", model, self._openrouter_key, OPENROUTER_BASE)

        # Groq fallback
        if self._groq_key and self._groq_model not in tried_models:
            yield ("groq", self._groq_model, self._groq_key, GROQ_BASE)

    def _do_stream(
        self,
        base_url: str,
        api_key: str,
        provider: str,
        model: str,
        messages: list,
        tools: list | None,
        timeout: int,
    ) -> Generator[dict, None, None]:
        """Execute a single streaming call."""
        endpoint = f"{base_url}/chat/completions"
        headers  = self._build_headers(api_key, provider)
        payload  = self._build_payload(model, messages, tools, stream=True)

        with requests.post(
            endpoint, json=payload, headers=headers, timeout=timeout, stream=True
        ) as resp:
            resp.raise_for_status()

            full_content  = ""
            buf           = ""
            tc_fragments: dict[int, dict] = {}
            p_tok = 0
            c_tok = 0

            for raw in resp.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                # Extract usage if present (some providers include it in stream)
                if "usage" in chunk:
                    usage = chunk["usage"]
                    p_tok = usage.get("prompt_tokens", p_tok)
                    c_tok = usage.get("completion_tokens", c_tok)

                choice = chunk.get("choices", [{}])[0]
                delta  = choice.get("delta", {})
                text   = delta.get("content") or ""

                full_content += text
                buf          += text

                # Yield complete sentences for streaming TTS
                while True:
                    m = _SENT_END.search(buf)
                    if not m:
                        break
                    sentence = buf[:m.start() + 1].strip()
                    buf      = buf[m.end():]
                    if sentence:
                        yield {"type": "sentence", "text": sentence}

                # Accumulate streaming tool-call fragments
                for tc in (delta.get("tool_calls") or []):
                    idx = tc.get("index", 0)
                    if idx not in tc_fragments:
                        tc_fragments[idx] = {
                            "id": "", "function": {"name": "", "arguments": ""}
                        }
                    frag = tc_fragments[idx]
                    frag["id"] = frag["id"] or tc.get("id", "")
                    fn = tc.get("function", {})
                    frag["function"]["name"]      += fn.get("name") or ""
                    frag["function"]["arguments"] += fn.get("arguments") or ""

                finish = choice.get("finish_reason")
                if finish in ("stop", "tool_calls", "length"):
                    break

            # Flush trailing content
            if buf.strip():
                yield {"type": "sentence", "text": buf.strip()}

            # Parse tool-call fragments
            tool_calls: list = []
            for idx in sorted(tc_fragments):
                frag = tc_fragments[idx]
                args = frag["function"]["arguments"]
                try:
                    args = json.loads(args)
                except Exception:
                    pass
                tool_calls.append({
                    "id":       frag["id"],
                    "function": {"name": frag["function"]["name"], "arguments": args},
                })

            # Estimate tokens from content length if not reported
            if p_tok == 0:
                p_tok = sum(len((m.get("content") or "").split()) for m in messages) * 2
            if c_tok == 0:
                c_tok = len(full_content.split()) * 2

            cost = self._estimate_cost(model, p_tok, c_tok) if provider == "openrouter" else 0.0
            with self._lock:
                self._record_usage(provider, model, p_tok, c_tok, cost, "success")

            yield {
                "type":       "done",
                "content":    full_content.strip(),
                "tool_calls": tool_calls,
            }

    # ── Simple text call ─────────────────────────────────────────────────

    def call_text(
        self,
        prompt: str,
        system: str | None = None,
        timeout: int = 120,
    ) -> str:
        """Simple text-only generation (no tools). Used by planner, dev_agent, etc."""
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        result = self.call(messages, tools=None, timeout=timeout)
        return result.get("content", "")

    # ── Status ───────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """
        Return current provider status for the dashboard.
        Never exposes API keys.
        """
        with self._lock:
            spent     = round(self._usage.get("total_spent", 0.0), 4)
            remaining = round(max(0, self._budget - spent), 4)
            exhausted = not self._is_budget_available()

            # Determine current active provider
            if self._openrouter_key and not exhausted and self._openrouter_models:
                active_provider = "OPENROUTER"
                active_model    = self._current_openrouter_model()
            elif self._groq_key:
                active_provider = "GROQ"
                active_model    = self._groq_model
            else:
                active_provider = "NONE"
                active_model    = ""

            return {
                "provider":            active_provider,
                "model":               active_model,
                "fallback":            "GROQ" if self._groq_key else "NONE",
                "budget":              self._budget,
                "spent":               spent,
                "remaining":           remaining,
                "budget_exhausted":    exhausted,
                "total_requests":      self._usage.get("total_requests", 0),
                "openrouter_requests": self._usage.get("openrouter_requests", 0),
                "groq_requests":       self._usage.get("groq_requests", 0),
            }

    # ── Budget reset ─────────────────────────────────────────────────────

    def reset_usage(self) -> None:
        """Reset all usage tracking. For admin use."""
        with self._lock:
            self._usage = dict(_EMPTY_USAGE)
            self._usage["last_reset"] = datetime.now(timezone.utc).isoformat()
            self._save_usage()
            print("[ProviderRouter] Usage tracking reset.")


# ── Singleton ────────────────────────────────────────────────────────────────

_router_instance: ProviderRouter | None = None
_router_lock = threading.Lock()


def get_router() -> ProviderRouter:
    """Get or create the singleton ProviderRouter instance."""
    global _router_instance
    if _router_instance is None:
        with _router_lock:
            if _router_instance is None:
                _router_instance = ProviderRouter()
    return _router_instance


def get_provider_status() -> dict:
    """Convenience function for dashboard integration."""
    try:
        return get_router().get_status()
    except Exception as e:
        return {
            "provider":         "ERROR",
            "model":            "",
            "fallback":         "NONE",
            "budget":           0.0,
            "spent":            0.0,
            "remaining":        0.0,
            "budget_exhausted": True,
            "error":            str(e),
        }
