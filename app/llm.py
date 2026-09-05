"""Thin LLM client for local (Ollama) or OpenAI-compatible endpoints.

Deliberately minimal: the assistant must keep working when no LLM is reachable,
so every call returns None on failure and callers fall back to deterministic
logic.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import httpx

from . import config


@dataclass
class LLMResult:
    text: str
    model: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Usage:
    """Per-request telemetry, surfaced in the UI to evidence model efficiency."""

    calls: list[dict] = field(default_factory=list)

    def add(self, purpose: str, r: LLMResult) -> None:
        self.calls.append(
            {
                "purpose": purpose,
                "model": r.model,
                "latency_ms": r.latency_ms,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "error": r.error,
            }
        )

    def summary(self) -> dict:
        return {
            "llm_calls": len(self.calls),
            "total_tokens": sum(c["prompt_tokens"] + c["completion_tokens"] for c in self.calls),
            "total_latency_ms": sum(c["latency_ms"] for c in self.calls),
            "models": sorted({c["model"] for c in self.calls}),
            "detail": self.calls,
        }


class LLMClient:
    def __init__(self) -> None:
        self.provider = config.LLM_PROVIDER
        self.model = config.LLM_MODEL
        self.fallback_model = config.LLM_MODEL_FALLBACK or None
        self.base_url = config.LLM_BASE_URL
        self._client = httpx.Client(timeout=config.LLM_TIMEOUT_SECONDS)
        self._healthy: bool | None = None

    @property
    def enabled(self) -> bool:
        return self.provider in ("ollama", "openai", "sarvam")

    def health(self, refresh: bool = False) -> bool:
        if not self.enabled:
            return False
        if self._healthy is not None and not refresh:
            return self._healthy
        try:
            if self.provider == "ollama":
                r = self._client.get(f"{self.base_url}/api/tags", timeout=5)
                self._healthy = r.status_code == 200
            elif self.provider == "sarvam":
                headers = {"api-subscription-key": config.LLM_API_KEY} if config.LLM_API_KEY else {}
                # Sarvam hasn't published a standard /v1/models endpoint yet in some versions,
                # but an OPTIONS or GET to the base URL usually suffices for a quick health check.
                r = self._client.get(f"{self.base_url}/v1/chat/completions", headers=headers, timeout=8)
                self._healthy = r.status_code != 401 and r.status_code < 500
            else:
                headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
                r = self._client.get(f"{self.base_url}/v1/models", headers=headers, timeout=8)
                self._healthy = r.status_code < 500
        except Exception:  # noqa: BLE001
            self._healthy = False
        return self._healthy

    # ------------------------------------------------------------------ core
    def chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        model: str | None = None,
        max_tokens: int = 512,
    ) -> LLMResult:
        model = model or self.model
        t0 = time.perf_counter()
        if not self.enabled:
            return LLMResult("", model, 0, error="llm_disabled")
        try:
            if self.provider == "ollama":
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "options": {"temperature": config.LLM_TEMPERATURE, "num_predict": max_tokens},
                }
                if json_mode:
                    payload["format"] = "json"
                r = self._client.post(f"{self.base_url}/api/chat", json=payload)
                r.raise_for_status()
                data = r.json()
                return LLMResult(
                    text=data.get("message", {}).get("content", ""),
                    model=model,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    prompt_tokens=data.get("prompt_eval_count", 0),
                    completion_tokens=data.get("eval_count", 0),
                )

            headers = {"Content-Type": "application/json"}
            if config.LLM_API_KEY:
                if self.provider == "sarvam":
                    headers["api-subscription-key"] = config.LLM_API_KEY
                else:
                    headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": config.LLM_TEMPERATURE,
                "max_tokens": max_tokens,
            }
            if json_mode:
                if self.provider == "sarvam":
                    # Some Sarvam models don't strict-enforce the response_format key yet,
                    # but we keep it here as the prompt explicitly demands JSON.
                    # We inject the JSON requirement broadly.
                    pass
                else:
                    payload["response_format"] = {"type": "json_object"}
            
            r = self._client.post(f"{self.base_url}/v1/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage") or {}
            return LLMResult(
                text=data["choices"][0]["message"]["content"] or "",
                model=model,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )
        except Exception as exc:  # noqa: BLE001
            self._healthy = False
            return LLMResult("", model, int((time.perf_counter() - t0) * 1000), error=str(exc)[:200])

    def chat_json(self, system: str, user: str, *, model: str | None = None, max_tokens: int = 512):
        res = self.chat(system, user, json_mode=True, model=model, max_tokens=max_tokens)
        return extract_json(res.text), res


_JSON_RE = re.compile(r"\{.*\}", re.S)


def extract_json(text: str) -> dict | None:
    """Small models wrap JSON in prose or fences. Dig it out."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    match = _JSON_RE.search(text)
    for candidate in (text, match.group(0) if match else None):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


llm = LLMClient()
