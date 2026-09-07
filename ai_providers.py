"""Small, testable adapters for the supported AI explanation providers."""

from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class AIConfig:
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""


@dataclass(frozen=True)
class AIResult:
    text: str
    total_tokens: int = 0


@dataclass(frozen=True)
class AIChunk:
    text: str
    total_tokens: int = 0


DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "ollama": "http://127.0.0.1:11434/v1",
}


def _base_url(config: AIConfig, allow_private_endpoint: bool) -> str:
    base = (config.base_url or DEFAULT_BASE_URLS.get(config.provider, "")).rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("AI API 網址格式不正確")
    if parsed.query or parsed.fragment:
        raise ValueError("AI API 網址不可包含 query 或 fragment")
    if (config.base_url or config.provider == "ollama") and not allow_private_endpoint:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
        except socket.gaierror as error:
            raise ValueError("無法解析 Ollama API 網址") from error
        if any(_is_private_address(address) for address in addresses):
            raise ValueError("部署環境不可連線至私人網路的 AI API")
        if parsed.scheme != "https":
            raise ValueError("部署環境的自訂 AI API 必須使用 HTTPS 公開網址")
    return base


def _is_private_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not address.is_global


def _raise(response):
    response.raise_for_status()
    return response.json()


def _openai_headers(config):
    return {"Authorization": f"Bearer {config.api_key}"}


def generate(config: AIConfig, prompt: str, client=None, *, allow_private_endpoint=False) -> AIResult:
    if config.provider == "gemini":
        from google import genai

        response = genai.Client(api_key=config.api_key).models.generate_content(
            model=config.model, contents=prompt
        )
        usage = getattr(response, "usage_metadata", None)
        return AIResult(response.text or "", getattr(usage, "total_token_count", 0) or 0)

    if client is None:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as http:
            return generate(config, prompt, http, allow_private_endpoint=allow_private_endpoint)

    http = client
    base = _base_url(config, allow_private_endpoint)
    if config.provider == "openai":
        data = _raise(http.post(
            f"{base}/responses", headers=_openai_headers(config),
            json={"model": config.model, "input": prompt, "store": False},
        ))
        text = "".join(
            part.get("text", "")
            for output in data.get("output", []) if output.get("type") == "message"
            for part in output.get("content", []) if part.get("type") == "output_text"
        )
        return AIResult(text, data.get("usage", {}).get("total_tokens", 0) or 0)
    if config.provider == "anthropic":
        data = _raise(http.post(
            f"{base}/messages",
            headers={"x-api-key": config.api_key, "anthropic-version": "2023-06-01"},
            json={"model": config.model, "max_tokens": 2048,
                  "messages": [{"role": "user", "content": prompt}]},
        ))
        usage = data.get("usage", {})
        text = "".join(part.get("text", "") for part in data.get("content", [])
                       if part.get("type") == "text")
        return AIResult(text, (usage.get("input_tokens", 0) or 0) +
                        (usage.get("output_tokens", 0) or 0))
    if config.provider == "ollama":
        headers = _openai_headers(AIConfig("ollama", config.model, config.api_key or "ollama"))
        data = _raise(http.post(
            f"{base}/chat/completions", headers=headers,
            json={"model": config.model, "messages": [{"role": "user", "content": prompt}]},
        ))
        choices = data.get("choices", [])
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        return AIResult(text, data.get("usage", {}).get("total_tokens", 0) or 0)
    raise ValueError("不支援的 AI provider")


def _sse_json(response):
    for line in response.iter_lines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def stream(config: AIConfig, prompt: str, client=None, *, allow_private_endpoint=False):
    if config.provider == "gemini":
        from google import genai

        chunks = genai.Client(api_key=config.api_key).models.generate_content_stream(
            model=config.model, contents=prompt
        )
        for chunk in chunks:
            usage = getattr(chunk, "usage_metadata", None)
            yield AIChunk(chunk.text or "", getattr(usage, "total_token_count", 0) or 0)
        return

    if client is None:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as http:
            yield from stream(config, prompt, http,
                              allow_private_endpoint=allow_private_endpoint)
        return

    http = client
    base = _base_url(config, allow_private_endpoint)
    if config.provider == "openai":
        request_args = (f"{base}/responses", _openai_headers(config),
                        {"model": config.model, "input": prompt, "store": False, "stream": True})
    elif config.provider == "anthropic":
        request_args = (f"{base}/messages",
                        {"x-api-key": config.api_key, "anthropic-version": "2023-06-01"},
                        {"model": config.model, "max_tokens": 2048,
                         "messages": [{"role": "user", "content": prompt}], "stream": True})
    elif config.provider == "ollama":
        request_args = (f"{base}/chat/completions",
                        _openai_headers(AIConfig("ollama", config.model, config.api_key or "ollama")),
                        {"model": config.model, "messages": [{"role": "user", "content": prompt}],
                         "stream": True, "stream_options": {"include_usage": True}})
    else:
        raise ValueError("不支援的 AI provider")

    anthropic_input_tokens = 0
    with http.stream("POST", request_args[0], headers=request_args[1], json=request_args[2]) as response:
        response.raise_for_status()
        for event in _sse_json(response):
            text, tokens = "", 0
            if config.provider == "openai":
                if event.get("type") == "response.output_text.delta":
                    text = event.get("delta", "")
                usage = (event.get("response") or {}).get("usage", {})
                tokens = usage.get("total_tokens", 0) or 0
            elif config.provider == "anthropic":
                if event.get("type") == "content_block_delta":
                    text = event.get("delta", {}).get("text", "")
                usage = event.get("usage") or (event.get("message") or {}).get("usage", {})
                anthropic_input_tokens = usage.get("input_tokens", 0) or anthropic_input_tokens
                if usage:
                    tokens = anthropic_input_tokens + (usage.get("output_tokens", 0) or 0)
            else:
                choices = event.get("choices", [])
                text = choices[0].get("delta", {}).get("content", "") if choices else ""
                tokens = event.get("usage", {}).get("total_tokens", 0) or 0
            if text or tokens:
                yield AIChunk(text, tokens)
