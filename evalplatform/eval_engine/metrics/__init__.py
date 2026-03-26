"""Evaluation metrics for chatbot conversations.

All concrete metrics are automatically registered with the
:data:`~platform.eval_engine.registry.metric_registry` on import.
"""

from __future__ import annotations

from evalplatform.eval_engine.metrics.base import (
    BaseMetric,
    ConversationTurn,
    EvalContext,
    MetricCategory,
    MetricResult,
)

# Import concrete metrics to trigger registration via @metric_registry.register
from evalplatform.eval_engine.metrics.faithfulness import FaithfulnessMetric
from evalplatform.eval_engine.metrics.relevance import RelevanceMetric
from evalplatform.eval_engine.metrics.hallucination import HallucinationMetric
from evalplatform.eval_engine.metrics.toxicity import ToxicityMetric
from evalplatform.eval_engine.metrics.coherence import CoherenceMetric
from evalplatform.eval_engine.metrics.completeness import CompletenessMetric
from evalplatform.eval_engine.metrics.context_adherence import ContextAdherenceMetric
from evalplatform.eval_engine.metrics.conversation_quality import ConversationQualityMetric
from evalplatform.eval_engine.metrics.latency import LatencyMetric
from evalplatform.eval_engine.metrics.cost import CostMetric
from evalplatform.eval_engine.metrics.custom import (
    CustomMetric,
    LLMCustomMetric,
    register_custom_metric,
    register_llm_custom_metric,
)

__all__ = [
    # Base
    "BaseMetric",
    "ConversationTurn",
    "EvalContext",
    "MetricCategory",
    "MetricResult",
    # Concrete metrics
    "FaithfulnessMetric",
    "RelevanceMetric",
    "HallucinationMetric",
    "ToxicityMetric",
    "CoherenceMetric",
    "CompletenessMetric",
    "ContextAdherenceMetric",
    "ConversationQualityMetric",
    "LatencyMetric",
    "CostMetric",
    # Custom
    "CustomMetric",
    "LLMCustomMetric",
    "register_custom_metric",
    "register_llm_custom_metric",
]
