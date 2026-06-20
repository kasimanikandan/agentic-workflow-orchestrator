"""Pluggable LLM provider interface + adapters for all major providers.

IMPORTANT: LLM is NOT used for orchestration (DAG scheduling).
LLM IS used WITHIN skills — individual tasks can call ctx.llm(messages, model).

This is a key distinction:
- Orchestration (DAG walk, concurrency, rate limits) = deterministic, no LLM needed
- Skills (individual task logic) = may need reasoning, can optionally call LLM

The orchestrator itself is always deterministic. LLM is just a tool skills can call.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class LlmResult:
    """Result from one LLM API call."""
    text: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    stop_reason: str = "stop"
    model: str = ""
    provider: str = ""


class LlmProvider(Protocol):
    """Interface that all LLM providers must implement."""
    name: str

    def complete(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        **opts: Any,
    ) -> LlmResult:
        """Call the LLM and return a result.

        Args:
            messages: OpenAI-format message list [{"role": "user", "content": "..."}]
            tools: Optional tool schema for function calling
            model: Model to use (overrides instance default)
            **opts: Provider-specific options (max_tokens, temperature, etc)
        """
        ...


# ---------------------------------------------------------------------------
# MockLLM — Deterministic, offline, for tests
# ---------------------------------------------------------------------------

class MockLLM:
    """Deterministic provider for tests/examples. No network, no API keys.

    Classifies text sentiment (positive/negative) based on keyword matching.
    Used in all examples and tests for zero-dependency, reproducible runs.
    """

    name = "mock"

    def __init__(self, model: str = "mock-1"):
        self.model = model

    def complete(self, messages, tools=None, model=None, **opts) -> LlmResult:
        text = messages[-1]["content"] if messages else ""
        lowered = str(text).lower()
        negative = any(w in lowered for w in ("cut", "miss", "down", "loss", "negative", "fall"))
        verdict = "net-negative" if negative else "net-positive"
        words = max(1, len(str(text).split()))
        return LlmResult(
            text=f'{{"label": "{verdict}", "confidence": 0.81}}',
            tokens_in=words,
            tokens_out=12,
            model=model or self.model,
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# Anthropic (Claude) — Recommended for reasoning
# ---------------------------------------------------------------------------

class AnthropicProvider:
    """Claude API adapter. Recommended for complex reasoning and tool use.

    Requires: pip install agentic-workflow-orchestrator[anthropic]
    Models: claude-opus-4-8 (default), claude-sonnet-4-6, claude-haiku-4-5
    """

    name = "anthropic"

    def __init__(self, model: str = "claude-opus-4-8", api_key: Optional[str] = None):
        self.model = model
        self._api_key = api_key

    def complete(self, messages, tools=None, model=None, **opts) -> LlmResult:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install 'anthropic>=0.7.0' to use AnthropicProvider") from exc

        client = anthropic.Anthropic(api_key=self._api_key)
        kwargs: Dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": opts.get("max_tokens", 1024),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        resp = client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        tool_calls = [
            {"name": b.name, "input": b.input, "id": b.id}
            for b in resp.content
            if getattr(b, "type", "") == "tool_use"
        ]
        return LlmResult(
            text=text,
            tool_calls=tool_calls,
            tokens_in=resp.usage.input_tokens,
            tokens_out=resp.usage.output_tokens,
            stop_reason=resp.stop_reason or "stop",
            model=resp.model,
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# OpenAI — High performance
# ---------------------------------------------------------------------------

class OpenAIProvider:
    """OpenAI API adapter (GPT-4, GPT-3.5).

    Requires: pip install agentic-workflow-orchestrator[openai]
    Models: gpt-4, gpt-4-turbo, gpt-3.5-turbo (default)
    """

    name = "openai"

    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        self.model = model
        self._api_key = api_key

    def complete(self, messages, tools=None, model=None, **opts) -> LlmResult:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install 'openai>=1.0.0' to use OpenAIProvider") from exc

        client = OpenAI(api_key=self._api_key)
        kwargs: Dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": opts.get("max_tokens", 1024),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        resp = client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        tool_calls = []
        if resp.choices[0].message.tool_calls:
            for tc in resp.choices[0].message.tool_calls:
                tool_calls.append({"name": tc.function.name, "input": tc.function.arguments, "id": tc.id})
        return LlmResult(
            text=text,
            tool_calls=tool_calls,
            tokens_in=resp.usage.prompt_tokens,
            tokens_out=resp.usage.completion_tokens,
            stop_reason=resp.choices[0].finish_reason or "stop",
            model=resp.model,
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# Google Gemini — Multimodal
# ---------------------------------------------------------------------------

class GeminiProvider:
    """Google Gemini API adapter.

    Requires: pip install agentic-workflow-orchestrator[gemini]
    Models: gemini-pro (default), gemini-pro-vision, gemini-1.5-pro
    """

    name = "gemini"

    def __init__(self, model: str = "gemini-1.5-pro", api_key: Optional[str] = None):
        self.model = model
        self._api_key = api_key

    def complete(self, messages, tools=None, model=None, **opts) -> LlmResult:
        try:
            import google.generativeai as genai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install 'google-generativeai>=0.3.0' to use GeminiProvider") from exc

        genai.configure(api_key=self._api_key)
        client = genai.GenerativeModel(model or self.model)

        # Convert OpenAI format to Gemini format
        gemini_messages = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            gemini_messages.append({"role": role, "parts": [msg["content"]]})

        resp = client.generate_content(
            contents=gemini_messages,
            generation_config=genai.GenerationConfig(max_output_tokens=opts.get("max_tokens", 1024)),
        )
        text = resp.text or ""
        return LlmResult(
            text=text,
            tool_calls=[],
            tokens_in=resp.usage_metadata.prompt_token_count,
            tokens_out=resp.usage_metadata.candidates_token_count,
            stop_reason=resp.candidates[0].finish_reason.name if resp.candidates else "stop",
            model=model or self.model,
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# xAI (Grok) — Latest frontier
# ---------------------------------------------------------------------------

class XAIProvider:
    """xAI Grok API adapter.

    Requires: pip install agentic-workflow-orchestrator[xai]
    Models: grok-beta (default)
    Uses OpenAI-compatible API.
    """

    name = "xai"

    def __init__(self, model: str = "grok-beta", api_key: Optional[str] = None):
        self.model = model
        self._api_key = api_key

    def complete(self, messages, tools=None, model=None, **opts) -> LlmResult:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install 'openai>=1.0.0' to use XAIProvider") from exc

        # xAI uses OpenAI-compatible API
        client = OpenAI(
            api_key=self._api_key,
            base_url="https://api.x.ai/v1",
        )
        kwargs: Dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": opts.get("max_tokens", 1024),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        resp = client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        tool_calls = []
        if resp.choices[0].message.tool_calls:
            for tc in resp.choices[0].message.tool_calls:
                tool_calls.append({"name": tc.function.name, "input": tc.function.arguments, "id": tc.id})
        return LlmResult(
            text=text,
            tool_calls=tool_calls,
            tokens_in=resp.usage.prompt_tokens,
            tokens_out=resp.usage.completion_tokens,
            stop_reason=resp.choices[0].finish_reason or "stop",
            model=resp.model,
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# Hugging Face / Local models
# ---------------------------------------------------------------------------

class HuggingFaceProvider:
    """Hugging Face Inference API or local models via transformers.

    Requires: pip install agentic-workflow-orchestrator[huggingface]
    Models: any Hugging Face model or local GGUF.
    Supports: transformers library or Hugging Face Inference API.
    """

    name = "huggingface"

    def __init__(self, model: str = "meta-llama/Llama-2-7b-chat-hf", api_key: Optional[str] = None):
        self.model = model
        self._api_key = api_key

    def complete(self, messages, tools=None, model=None, **opts) -> LlmResult:
        try:
            from transformers import pipeline
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install 'transformers>=4.30.0' to use HuggingFaceProvider") from exc

        pipe = pipeline("text-generation", model=model or self.model)
        text_input = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        resp = pipe(text_input, max_new_tokens=opts.get("max_tokens", 1024))
        text = resp[0]["generated_text"] if resp else ""
        return LlmResult(
            text=text,
            tool_calls=[],
            tokens_in=len(text_input.split()),
            tokens_out=len(text.split()),
            model=model or self.model,
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# Azure OpenAI
# ---------------------------------------------------------------------------

class AzureOpenAIProvider:
    """Azure OpenAI API adapter.

    Requires: pip install agentic-workflow-orchestrator[azure]
    Uses OpenAI-compatible API with Azure credentials.
    """

    name = "azure"

    def __init__(
        self,
        deployment_name: str,
        api_key: Optional[str] = None,
        api_version: str = "2024-02-01",
        azure_endpoint: Optional[str] = None,
    ):
        self.deployment = deployment_name
        self._api_key = api_key
        self._api_version = api_version
        self._endpoint = azure_endpoint
        self.model = deployment_name

    def complete(self, messages, tools=None, model=None, **opts) -> LlmResult:
        try:
            from openai import AzureOpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install 'openai>=1.0.0' to use AzureOpenAIProvider") from exc

        client = AzureOpenAI(
            api_key=self._api_key,
            azure_endpoint=self._endpoint,
            api_version=self._api_version,
        )
        kwargs: Dict[str, Any] = {
            "deployment_id": self.deployment,
            "max_tokens": opts.get("max_tokens", 1024),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        resp = client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        tool_calls = []
        if resp.choices[0].message.tool_calls:
            for tc in resp.choices[0].message.tool_calls:
                tool_calls.append({"name": tc.function.name, "input": tc.function.arguments, "id": tc.id})
        return LlmResult(
            text=text,
            tool_calls=tool_calls,
            tokens_in=resp.usage.prompt_tokens,
            tokens_out=resp.usage.completion_tokens,
            stop_reason=resp.choices[0].finish_reason or "stop",
            model=self.deployment,
            provider=self.name,
        )


__all__ = [
    "LlmProvider",
    "LlmResult",
    "MockLLM",
    "AnthropicProvider",
    "OpenAIProvider",
    "GeminiProvider",
    "XAIProvider",
    "HuggingFaceProvider",
    "AzureOpenAIProvider",
]
