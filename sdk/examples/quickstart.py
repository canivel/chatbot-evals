#!/usr/bin/env python3
"""Chatbot Evals SDK - Quick Start Example.

Shows the simplest way to evaluate chatbot conversations.

Usage:
    export OPENAI_API_KEY=sk-...
    python examples/quickstart.py
"""

import asyncio
from chatbot_evals import ChatbotEvals, Conversation, Message


async def main():
    # 1. Create the client
    ce = ChatbotEvals(judge_model="gpt-4o-mini")

    # 2. Define conversations to evaluate
    conversations = [
        Conversation(
            messages=[
                Message(role="user", content="What is your return policy?"),
                Message(
                    role="assistant",
                    content="Our return policy allows returns within 30 days of purchase. "
                    "Items must be in original condition with receipt.",
                ),
            ],
            context="Return Policy: Customers may return items within 30 days. "
            "Items must be unused and in original packaging. Receipt required.",
            ground_truth="Returns accepted within 30 days with receipt.",
        ),
        Conversation(
            messages=[
                Message(role="user", content="Can I get a discount?"),
                Message(
                    role="assistant",
                    content="We have a 50% off sale on everything! Use code SAVE50.",
                ),
            ],
            context="Current promotions: Free shipping on orders over $75.",
            ground_truth="Check website for current deals.",
        ),
    ]

    # 3. Evaluate
    report = await ce.evaluate_dataset(
        conversations,
        metrics=["faithfulness", "relevance", "hallucination"],
    )

    # 4. Print results
    print(f"Overall Score: {report.summary}")
    print(f"\nMetric Averages:")
    for metric, score in report.metric_averages.items():
        print(f"  {metric}: {score:.2%}")

    print(f"\nPer-conversation:")
    for result in report.results:
        print(f"  {result.conversation_id}: {result.overall_score:.2%}")
        for flag in result.flags:
            print(f"    FLAG: {flag}")

    # 5. Export
    report.to_html("eval_report.html")
    print("\nHTML report saved to eval_report.html")


if __name__ == "__main__":
    asyncio.run(main())
