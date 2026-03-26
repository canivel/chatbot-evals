"""Multi-provider LLM client supporting OpenAI, Anthropic Claude, and Google Gemini.

Usage::

    from evalplatform.llm import create_llm_client, LLMResponse

    client = create_llm_client()  # auto-detects from env
    response = await client.chat("gpt-4o", messages=[...])
"""

from evalplatform.llm.client import (
    BaseLLMClient,
    LLMResponse,
    OpenAIClient,
    AnthropicClient,
    GeminiClient,
    MultiProviderClient,
    create_llm_client,
)

__all__ = [
    "BaseLLMClient",
    "LLMResponse",
    "OpenAIClient",
    "AnthropicClient",
    "GeminiClient",
    "MultiProviderClient",
    "create_llm_client",
]
