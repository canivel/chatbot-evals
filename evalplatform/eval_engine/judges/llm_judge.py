"""LLM-as-Judge implementation using the OpenAI SDK."""

from __future__ import annotations

import json
import os
import asyncio
from typing import Any

from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import structlog

from evalplatform.eval_engine.judges.base_judge import BaseJudge, JudgeVerdict

logger = structlog.get_logger(__name__)

# Exceptions that warrant a retry (transient failures)
_RETRYABLE = (
    TimeoutError,
    ConnectionError,
    json.JSONDecodeError,
)


class LLMJudge(BaseJudge):
    """Judge that uses an LLM (via OpenAI SDK) to evaluate inputs.

    Supports OpenAI and any OpenAI-compatible API via base_url.
    Responses are expected to be JSON and are parsed into a :class:`JudgeVerdict`.

    Args:
        model: The model identifier (e.g. ``"gpt-4o"``).
        temperature: Sampling temperature for the judge model.
        max_tokens: Maximum tokens in the judge response.
        max_retries: Number of retry attempts on transient failures.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        max_tokens: int = 4096,
        max_retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.timeout = timeout
        self._client = AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )

    # -- Core judge method ---------------------------------------------------

    async def judge(self, input_data: dict[str, Any]) -> JudgeVerdict:
        """Run the LLM judge on a single input.

        ``input_data`` must contain:
        - ``prompt`` (str): The fully-formatted prompt to send.

        Optionally:
        - ``system_message`` (str): A system message for the judge.

        Returns:
            Parsed :class:`JudgeVerdict`.
        """
        prompt = input_data.get("prompt", "")
        system_message = input_data.get(
            "system_message",
            "You are an expert evaluation judge. Always respond with valid JSON.",
        )

        if not prompt:
            raise ValueError("input_data must contain a non-empty 'prompt' key")

        raw_response = await self._call_llm(system_message, prompt)
        return self._parse_response(raw_response)

    # -- Batch evaluation ----------------------------------------------------

    async def judge_batch(
        self,
        inputs: list[dict[str, Any]],
        max_concurrency: int = 5,
    ) -> list[JudgeVerdict]:
        """Evaluate a batch of inputs concurrently.

        Args:
            inputs: List of input dicts (same schema as :meth:`judge`).
            max_concurrency: Maximum number of concurrent LLM calls.

        Returns:
            List of verdicts, one per input (order preserved).
        """
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _limited(data: dict[str, Any]) -> JudgeVerdict:
            async with semaphore:
                return await self.judge(data)

        tasks = [_limited(inp) for inp in inputs]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    # -- Internal helpers ----------------------------------------------------

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_llm(self, system_message: str, user_message: str) -> str:
        """Make an LLM call with retry logic.

        Returns:
            The raw text content of the LLM response.
        """
        logger.debug(
            "llm_judge_call",
            model=self.model,
            prompt_length=len(user_message),
        )

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )

        content: str = response.choices[0].message.content or ""

        if not content.strip():
            raise ValueError("LLM returned an empty response")

        logger.debug("llm_judge_response", response_length=len(content))
        return content

    def _parse_response(self, raw: str) -> JudgeVerdict:
        """Parse a raw LLM response (expected JSON) into a JudgeVerdict."""
        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("llm_judge_parse_failure", raw_response=raw[:500])
            # Return a low-confidence fallback verdict
            return JudgeVerdict(
                score=0.0,
                reasoning="Failed to parse LLM judge response as JSON.",
                confidence=0.0,
                raw_response=raw,
            )

        score = float(data.get("score", 0.0))
        score = max(0.0, min(1.0, score))

        reasoning = data.get("reasoning", "")
        confidence = float(data.get("confidence", 0.8))
        confidence = max(0.0, min(1.0, confidence))

        return JudgeVerdict(
            score=score,
            reasoning=reasoning,
            confidence=confidence,
            raw_response=raw,
            metadata={k: v for k, v in data.items() if k not in ("score", "reasoning", "confidence")},
        )

    def __repr__(self) -> str:
        return f"<LLMJudge model={self.model!r} temp={self.temperature}>"
