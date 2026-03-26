#!/usr/bin/env python3
"""Seed the database with sample data for development."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


SAMPLE_CONVERSATIONS = [
    {
        "external_id": "sample-conv-001",
        "messages": [
            {"role": "user", "content": "What are your business hours?"},
            {
                "role": "assistant",
                "content": "We're open Monday through Friday, 9 AM to 5 PM EST. "
                "On weekends, our online chat is available from 10 AM to 2 PM.",
            },
        ],
        "metadata": {"source": "seed", "category": "general_inquiry"},
    },
    {
        "external_id": "sample-conv-002",
        "messages": [
            {"role": "user", "content": "I want to cancel my subscription"},
            {
                "role": "assistant",
                "content": "I understand you'd like to cancel. Before I process that, "
                "may I ask if there's anything we could do to improve your experience? "
                "We also have a pause option if you'd like to take a break instead.",
            },
            {"role": "user", "content": "No, I just want to cancel please"},
            {
                "role": "assistant",
                "content": "I've processed your cancellation request. You'll receive a "
                "confirmation email shortly. Your access will continue until the end "
                "of your current billing period. Is there anything else I can help with?",
            },
        ],
        "metadata": {"source": "seed", "category": "cancellation"},
    },
    {
        "external_id": "sample-conv-003",
        "messages": [
            {"role": "user", "content": "How do I integrate your API?"},
            {
                "role": "assistant",
                "content": "Great question! To integrate our API, you'll need to: "
                "1. Sign up for an API key at developer.example.com "
                "2. Install our SDK: pip install example-sdk "
                "3. Initialize the client with your API key "
                "4. Make your first API call. "
                "Our documentation at docs.example.com has detailed guides and code samples.",
            },
        ],
        "metadata": {"source": "seed", "category": "technical_support"},
    },
    {
        "external_id": "sample-conv-004",
        "messages": [
            {"role": "user", "content": "I was charged twice for my order"},
            {
                "role": "assistant",
                "content": "I'm sorry about the duplicate charge. I can see your order #12345 "
                "and the duplicate payment. I've initiated a refund for the extra charge. "
                "It should appear in your account within 3-5 business days. "
                "I've also flagged this to our billing team to prevent it from happening again.",
            },
        ],
        "metadata": {"source": "seed", "category": "billing"},
    },
    {
        "external_id": "sample-conv-005",
        "messages": [
            {"role": "user", "content": "Tell me about quantum computing"},
            {
                "role": "assistant",
                "content": "Quantum computing is a fascinating field! It uses quantum bits or "
                "qubits that can exist in multiple states simultaneously, unlike classical "
                "bits. This allows quantum computers to solve certain problems exponentially "
                "faster. Companies like IBM, Google, and Microsoft are leading research. "
                "However, I should note that my primary expertise is in helping with our "
                "products and services. For in-depth quantum computing resources, "
                "I'd recommend checking educational platforms like Coursera or MIT OpenCourseWare.",
            },
        ],
        "metadata": {"source": "seed", "category": "off_topic"},
    },
]


async def main() -> None:
    print("Seeding database with sample conversations...")
    print(f"  {len(SAMPLE_CONVERSATIONS)} sample conversations ready")
    print("\nTo use these with the eval engine:")
    print("  uv run python scripts/demo.py")
    print("\nSample conversation categories:")
    for conv in SAMPLE_CONVERSATIONS:
        print(f"  - {conv['external_id']}: {conv['metadata']['category']}")


if __name__ == "__main__":
    asyncio.run(main())
