"""Multi-provider LLM client without litellm.

Supports OpenAI, Anthropic Claude, and Google Gemini via their native SDKs.
Provider is auto-detected from the model name or can be specified explicitly.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class LLMResponse(BaseModel):
    """Unified response from any LLM provider."""

    content: str = ""
    model: str = ""
    provider: str = ""
    usage: dict[str, int] = Field(default_factory=dict)
    raw_response: Any = Field(default=None, exclude=True)

    @property
    def total_tokens(self) -> int:
        return self.usage.get("total_tokens", 0)


# ---------------------------------------------------------------------------
# Base client
# ---------------------------------------------------------------------------

class BaseLLMClient(ABC):
    """Abstract base for LLM provider clients."""

    provider_name: str = "base"

    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        timeout: float = 60.0,
    ) -> LLMResponse:
        """Send a chat completion request."""

    def supports_model(self, model: str) -> bool:
        """Check if this client supports the given model name."""
        return False


# ---------------------------------------------------------------------------
# OpenAI client
# ---------------------------------------------------------------------------

class OpenAIClient(BaseLLMClient):
    """OpenAI API client using the official openai SDK."""

    provider_name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
        )

    def supports_model(self, model: str) -> bool:
        return model.startswith(("gpt-", "o1", "o3", "o4"))

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        timeout: float = 60.0,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=content,
            model=response.model,
            provider="openai",
            usage=usage,
            raw_response=response,
        )


# ---------------------------------------------------------------------------
# Anthropic Claude client
# ---------------------------------------------------------------------------

class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API client using the official anthropic SDK."""

    provider_name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")

    def supports_model(self, model: str) -> bool:
        return "claude" in model.lower()

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        timeout: float = 60.0,
    ) -> LLMResponse:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=timeout,
        )

        # Separate system message from conversation
        system_content = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content += msg["content"] + "\n"
            else:
                chat_messages.append(msg)

        # If json_mode, append instruction to system prompt
        if json_mode:
            system_content += "\nYou must respond with valid JSON only. No other text."

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_content.strip():
            kwargs["system"] = system_content.strip()

        response = await client.messages.create(**kwargs)
        content = response.content[0].text if response.content else ""

        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

        return LLMResponse(
            content=content,
            model=response.model,
            provider="anthropic",
            usage=usage,
            raw_response=response,
        )


# ---------------------------------------------------------------------------
# Google Gemini client
# ---------------------------------------------------------------------------

class GeminiClient(BaseLLMClient):
    """Google Gemini API client using the official google-genai SDK."""

    provider_name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")

    def supports_model(self, model: str) -> bool:
        return "gemini" in model.lower()

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        timeout: float = 60.0,
    ) -> LLMResponse:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)

        # Convert messages to Gemini format
        system_instruction = ""
        contents = []
        for msg in messages:
            if msg["role"] == "system":
                system_instruction += msg["content"] + "\n"
            elif msg["role"] == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=msg["content"])],
                ))
            elif msg["role"] == "assistant":
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=msg["content"])],
                ))

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system_instruction.strip():
            config.system_instruction = system_instruction.strip()
        if json_mode:
            config.response_mime_type = "application/json"

        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        content = response.text or ""

        usage = {}
        if response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "completion_tokens": response.usage_metadata.candidates_token_count or 0,
                "total_tokens": response.usage_metadata.total_token_count or 0,
            }

        return LLMResponse(
            content=content,
            model=model,
            provider="gemini",
            usage=usage,
            raw_response=response,
        )


# ---------------------------------------------------------------------------
# Multi-provider router
# ---------------------------------------------------------------------------

class MultiProviderClient(BaseLLMClient):
    """Routes requests to the correct provider based on model name.

    Auto-detects provider from model name:
    - gpt-*, o1*, o3*, o4* -> OpenAI
    - claude-* -> Anthropic
    - gemini-* -> Google Gemini

    Falls back to OpenAI for unknown models (supports OpenAI-compatible APIs).
    """

    provider_name = "multi"

    def __init__(self) -> None:
        self._clients: dict[str, BaseLLMClient] = {}

    def _get_client(self, model: str) -> BaseLLMClient:
        """Resolve the correct client for a model name."""
        model_lower = model.lower()

        if "claude" in model_lower:
            if "anthropic" not in self._clients:
                self._clients["anthropic"] = AnthropicClient()
            return self._clients["anthropic"]

        if "gemini" in model_lower:
            if "gemini" not in self._clients:
                self._clients["gemini"] = GeminiClient()
            return self._clients["gemini"]

        # Default to OpenAI (also handles OpenAI-compatible endpoints)
        if "openai" not in self._clients:
            self._clients["openai"] = OpenAIClient()
        return self._clients["openai"]

    def supports_model(self, model: str) -> bool:
        return True  # Routes to appropriate provider

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        timeout: float = 60.0,
    ) -> LLMResponse:
        client = self._get_client(model)
        logger.debug("llm_routing", model=model, provider=client.provider_name)
        return await client.chat(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            timeout=timeout,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_llm_client(provider: str | None = None) -> BaseLLMClient:
    """Create an LLM client.

    Args:
        provider: Force a specific provider ("openai", "anthropic", "gemini").
            If None, returns a MultiProviderClient that auto-routes by model name.

    Returns:
        An LLM client instance.
    """
    if provider == "openai":
        return OpenAIClient()
    elif provider == "anthropic":
        return AnthropicClient()
    elif provider == "gemini":
        return GeminiClient()
    else:
        return MultiProviderClient()
