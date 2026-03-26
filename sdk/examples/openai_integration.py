#!/usr/bin/env python3
"""Chatbot Evals SDK - OpenAI Integration Example.

Shows how to wrap an OpenAI client for automatic tracing and evaluation.

Usage:
    export OPENAI_API_KEY=sk-...
    python examples/openai_integration.py
"""

import asyncio
from openai import AsyncOpenAI
from chatbot_evals.integrations import OpenAIWrapper


async def main():
    # Wrap your existing OpenAI client
    client = AsyncOpenAI()
    traced = OpenAIWrapper(
        client,
        metrics=["faithfulness", "toxicity", "coherence"],
        auto_eval=True,
    )

    # Use exactly like the normal OpenAI client
    response = await traced.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful customer support agent."},
            {"role": "user", "content": "I need to return a defective product."},
        ],
    )

    print(f"Response: {response.choices[0].message.content}")

    # Get accumulated eval results
    report = await traced.get_eval_report()
    if report:
        print(f"\nEval Score: {report.metric_averages}")


if __name__ == "__main__":
    asyncio.run(main())
