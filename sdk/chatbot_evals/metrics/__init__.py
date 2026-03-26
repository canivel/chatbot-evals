"""Metric access and custom metric creation for the chatbot-evals SDK.

Re-exports the custom metric decorators and provides access to all built-in
metrics through the evaluation engine's registry.

Built-in metrics available via string name
------------------------------------------
- ``"faithfulness"`` -- Checks if the response is grounded in provided context.
- ``"relevance"`` -- Checks if the response addresses the user's question.
- ``"hallucination"`` -- Detects fabricated claims not in context.
- ``"toxicity"`` -- Detects harmful or unsafe content.
- ``"coherence"`` -- Evaluates logical flow and clarity.
- ``"completeness"`` -- Evaluates whether the response fully answers the question.
- ``"context_adherence"`` -- Checks adherence to retrieved context.
- ``"conversation_quality"`` -- Overall multi-turn conversation quality.
- ``"latency"`` -- Response time evaluation (metadata-based).
- ``"cost"`` -- Token cost evaluation (metadata-based).

Custom metrics
--------------
Create your own metrics with decorators::

    from chatbot_evals.metrics import custom_metric, llm_metric

    @custom_metric(name="my_check", description="My custom check")
    async def my_check(conversation):
        return 0.85

    @llm_metric(
        name="helpfulness",
        prompt="Rate helpfulness 0-1: {response}",
    )
    def helpfulness():
        pass
"""

from __future__ import annotations

from chatbot_evals.metrics.custom import custom_metric, llm_metric

__all__ = [
    "custom_metric",
    "llm_metric",
]
