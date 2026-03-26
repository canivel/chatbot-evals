#!/usr/bin/env python3
"""Demo script to showcase the eval engine on sample conversations.

Usage:
    uv run python scripts/demo.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evalplatform.eval_engine.metrics.base import ConversationTurn, EvalContext
from evalplatform.eval_engine.registry import metric_registry
from evalplatform.eval_engine.engine import EvalEngine, EvalConfig
from evalplatform.reports.generator import ReportGenerator
from evalplatform.reports.exporters import ReportExporter

# Import metrics to trigger registration
import evalplatform.eval_engine.metrics.faithfulness  # noqa: F401
import evalplatform.eval_engine.metrics.relevance  # noqa: F401
import evalplatform.eval_engine.metrics.hallucination  # noqa: F401
import evalplatform.eval_engine.metrics.coherence  # noqa: F401
import evalplatform.eval_engine.metrics.completeness  # noqa: F401
import evalplatform.eval_engine.metrics.toxicity  # noqa: F401
import evalplatform.eval_engine.metrics.context_adherence  # noqa: F401
import evalplatform.eval_engine.metrics.conversation_quality  # noqa: F401
import evalplatform.eval_engine.metrics.latency  # noqa: F401
import evalplatform.eval_engine.metrics.cost  # noqa: F401

# Sample conversations to evaluate
SAMPLE_CONVERSATIONS = [
    {
        "id": "conv-001",
        "messages": [
            {"role": "user", "content": "What is your return policy?"},
            {
                "role": "assistant",
                "content": "Our return policy allows returns within 30 days of purchase. "
                "Items must be in original condition with receipt. Refunds are processed "
                "within 5-7 business days to your original payment method.",
            },
        ],
        "ground_truth": "Returns accepted within 30 days with receipt. Items must be in original condition.",
        "retrieved_context": "Return Policy: Customers may return items within 30 days of purchase. "
        "Items must be unused and in original packaging. A valid receipt is required. "
        "Refunds are processed in 5-7 business days.",
    },
    {
        "id": "conv-002",
        "messages": [
            {"role": "user", "content": "Can I get a discount on my order?"},
            {
                "role": "assistant",
                "content": "I'd be happy to help! We currently have a 20% off sale on all items. "
                "Use code SAVE20 at checkout. We also offer free shipping on orders over $50.",
            },
        ],
        "ground_truth": "Current promotions vary. Check the website for active deals.",
        "retrieved_context": "Current Promotions: Check website for latest deals. "
        "Free shipping on orders over $75.",
    },
    {
        "id": "conv-003",
        "messages": [
            {"role": "user", "content": "I'm having trouble logging into my account"},
            {
                "role": "assistant",
                "content": "I'm sorry to hear that. Let me help you with that. "
                "First, try clearing your browser cache and cookies. "
                "If that doesn't work, you can reset your password by clicking "
                "'Forgot Password' on the login page. If you're still having issues, "
                "I can escalate this to our technical support team.",
            },
        ],
        "ground_truth": "Standard troubleshooting: clear cache, reset password, escalate if needed.",
        "retrieved_context": "Login Issues FAQ: 1. Clear browser cache 2. Try incognito mode "
        "3. Reset password via 'Forgot Password' link 4. Contact support if issue persists.",
    },
]


async def main() -> None:
    print("=" * 60)
    print("CHATBOT EVAL PLATFORM - DEMO")
    print("=" * 60)

    # Initialize registry and engine
    print(f"\nAvailable metrics: {[m['name'] for m in metric_registry.list_metrics()]}")

    # Prepare eval contexts
    conversations = []
    for conv in SAMPLE_CONVERSATIONS:
        turns = [ConversationTurn(role=m["role"], content=m["content"]) for m in conv["messages"]]
        ctx = EvalContext(
            conversation=turns,
            ground_truth=conv.get("ground_truth"),
            retrieved_context=conv.get("retrieved_context"),
            metadata={"conversation_id": conv["id"]},
        )
        conversations.append(ctx)

    # Run eval
    print(f"\nEvaluating {len(conversations)} conversations...")
    engine = EvalEngine()
    config = EvalConfig(
        metric_names=["faithfulness", "relevance", "hallucination", "coherence", "completeness"],
    )

    eval_run = await engine.run_eval(conversations, config)

    # Generate report from conversation results
    results = []
    for i, conv_result in enumerate(eval_run.conversation_results):
        conv_id = SAMPLE_CONVERSATIONS[i % len(SAMPLE_CONVERSATIONS)]["id"]
        for mr in conv_result.metric_results:
            results.append({
                "conversation_id": conv_id,
                "metric_name": mr.metric_name,
                "score": mr.score,
                "explanation": mr.explanation,
            })

    generator = ReportGenerator()
    report = generator.generate_eval_report("demo-run-001", results)

    # Export
    exporter = ReportExporter()

    print("\n" + "=" * 60)
    print("EVAL RESULTS")
    print("=" * 60)

    for ms in report.metric_summaries:
        status = "PASS" if ms.mean_score >= 0.7 else "WARN" if ms.mean_score >= 0.4 else "FAIL"
        print(f"  [{status}] {ms.metric_name}: {ms.mean_score:.4f} (pass rate: {ms.pass_rate:.2%})")

    print(f"\n  Overall Score: {report.overall_score:.4f}")
    print(f"  Conversations: {report.total_conversations}")

    if report.recommendations:
        print("\n  Recommendations:")
        for rec in report.recommendations:
            print(f"    - {rec}")

    # Save HTML report
    html = exporter.to_html(report)
    report_path = Path(__file__).parent.parent / "demo_report.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"\n  HTML report saved to: {report_path}")

    # Save JSON report
    json_report = exporter.to_json(report)
    json_path = Path(__file__).parent.parent / "demo_report.json"
    json_path.write_text(json_report, encoding="utf-8")
    print(f"  JSON report saved to: {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
