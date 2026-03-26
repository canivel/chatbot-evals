"""Chatbot evaluation engine.

This package provides the core evaluation engine for the chatbot-evals
platform, including metrics, judges, and the orchestration pipeline.
"""

from __future__ import annotations

from evalplatform.eval_engine.engine import EvalConfig, EvalEngine, EvalRun
from evalplatform.eval_engine.pipeline import EvalPipeline, PipelineConfig, PipelineResult
from evalplatform.eval_engine.registry import MetricRegistry, metric_registry

__all__ = [
    "EvalConfig",
    "EvalEngine",
    "EvalRun",
    "EvalPipeline",
    "MetricRegistry",
    "PipelineConfig",
    "PipelineResult",
    "metric_registry",
]
