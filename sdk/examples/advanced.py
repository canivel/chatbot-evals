#!/usr/bin/env python3
"""Chatbot Evals SDK - Advanced Usage Examples.

Demonstrates datasets, custom metrics, tracing, integrations, and callbacks.

Usage:
    export OPENAI_API_KEY=sk-...
    python examples/advanced.py
"""

import asyncio
from chatbot_evals import (
    ChatbotEvals,
    Conversation,
    Dataset,
    Message,
    evaluate,
)
from chatbot_evals.callbacks import PrintCallback, TqdmCallback
from chatbot_evals.metrics.custom import custom_metric, llm_metric
from chatbot_evals.datasets import DatasetLoader
from chatbot_evals.tracing import Tracer


# ---------------------------------------------------------------------------
# Example 1: Load dataset from file
# ---------------------------------------------------------------------------
async def example_dataset_loading():
    """Load conversations from various formats."""
    print("=== Dataset Loading ===")

    # From a JSON file
    # conversations = DatasetLoader.from_json("conversations.json")

    # From a JSONL file
    # conversations = DatasetLoader.from_jsonl("conversations.jsonl")

    # From a CSV
    # conversations = DatasetLoader.from_csv("data.csv", mapping={
    #     "user_col": "question",
    #     "assistant_col": "answer",
    #     "context_col": "context",
    # })

    # From a list of dicts
    conversations = DatasetLoader.from_dict_list([
        {
            "messages": [
                {"role": "user", "content": "How do I reset my password?"},
                {"role": "assistant", "content": "Go to Settings > Security > Reset Password."},
            ],
            "context": "Password Reset: Settings > Security > Change Password",
        },
        {
            "messages": [
                {"role": "user", "content": "What payment methods do you accept?"},
                {"role": "assistant", "content": "We accept Visa, Mastercard, and PayPal."},
            ],
            "context": "Payment: Visa, Mastercard, American Express, PayPal, Apple Pay",
        },
    ])

    # Create a named dataset
    dataset = Dataset(conversations=conversations, name="support-bot-v2")
    print(f"Loaded {len(dataset)} conversations")
    return dataset


# ---------------------------------------------------------------------------
# Example 2: Custom metrics
# ---------------------------------------------------------------------------
async def example_custom_metrics():
    """Define and use custom evaluation metrics."""
    print("\n=== Custom Metrics ===")

    # Function-based custom metric
    @custom_metric(name="response_length", description="Checks response is not too short")
    async def response_length(conversation: Conversation) -> float:
        last_assistant = None
        for msg in reversed(conversation.messages):
            if msg.role == "assistant":
                last_assistant = msg.content
                break
        if not last_assistant:
            return 0.0
        length = len(last_assistant.split())
        if length < 5:
            return 0.2
        elif length < 20:
            return 0.7
        else:
            return 1.0

    # LLM-based custom metric
    @llm_metric(
        name="empathy",
        prompt="""Evaluate if this customer support response shows empathy and understanding.

User: {question}
Response: {response}

Rate empathy from 0.0 (cold/robotic) to 1.0 (warm/empathetic).
Respond with JSON: {{"score": float, "reasoning": "..."}}'""",
    )
    def empathy():
        pass

    # Use custom metrics alongside built-in ones
    conversations = [
        Conversation.from_messages([
            {"role": "user", "content": "I'm frustrated, my order hasn't arrived!"},
            {"role": "assistant", "content": "I understand your frustration and I'm sorry for the delay. Let me look into your order right away and find out what happened."},
        ]),
    ]

    report = await evaluate(
        conversations,
        metrics=["faithfulness", "response_length", "empathy"],
        judge_model="gpt-4o-mini",
    )

    for metric, score in report.metric_averages.items():
        print(f"  {metric}: {score:.2%}")


# ---------------------------------------------------------------------------
# Example 3: Progress callbacks
# ---------------------------------------------------------------------------
async def example_callbacks():
    """Use callbacks to track evaluation progress."""
    print("\n=== Callbacks ===")

    conversations = [
        Conversation.from_messages([
            {"role": "user", "content": f"Question {i}"},
            {"role": "assistant", "content": f"Answer {i}"},
        ])
        for i in range(5)
    ]

    # Print callback shows progress to stdout
    report = await evaluate(
        conversations,
        metrics=["coherence"],
        callbacks=[PrintCallback()],
        judge_model="gpt-4o-mini",
    )
    print(f"Completed: {len(report.results)} conversations evaluated")


# ---------------------------------------------------------------------------
# Example 4: Tracing
# ---------------------------------------------------------------------------
async def example_tracing():
    """Use the tracer to capture chatbot interactions."""
    print("\n=== Tracing ===")

    tracer = Tracer(project="my-chatbot")

    # Simulate a chatbot interaction with spans
    with tracer.span("user_request") as span:
        span.set_attribute("user.message", "What's the weather?")

        with tracer.span("retrieval") as retrieval:
            retrieval.set_attribute("source", "weather_api")
            retrieval.set_attribute("context", "Current weather: 72F, sunny")

        with tracer.span("llm_call") as llm:
            llm.set_attribute("model", "gpt-4o")
            llm.set_attribute("response", "It's currently 72F and sunny!")

    # Convert traces to conversations for evaluation
    conversations = tracer.to_conversations()
    print(f"Captured {len(conversations)} conversations from traces")


# ---------------------------------------------------------------------------
# Example 5: Using with different providers
# ---------------------------------------------------------------------------
async def example_multi_provider():
    """Use different LLM providers as judges."""
    print("\n=== Multi-Provider ===")

    conversations = [
        Conversation.from_messages([
            {"role": "user", "content": "Explain quantum computing"},
            {"role": "assistant", "content": "Quantum computing uses qubits that can be in superposition."},
        ]),
    ]

    # Use OpenAI as judge
    ce_openai = ChatbotEvals(judge_model="gpt-4o-mini")
    # result = await ce_openai.evaluate(conversations[0], metrics=["coherence"])

    # Use Claude as judge
    ce_claude = ChatbotEvals(judge_model="claude-sonnet-4-20250514")
    # result = await ce_claude.evaluate(conversations[0], metrics=["coherence"])

    # Use Gemini as judge
    ce_gemini = ChatbotEvals(judge_model="gemini-2.0-flash")
    # result = await ce_gemini.evaluate(conversations[0], metrics=["coherence"])

    print("Multi-provider support: OpenAI, Claude, Gemini")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    dataset = await example_dataset_loading()
    # Uncomment the following when API keys are set:
    # await example_custom_metrics()
    # await example_callbacks()
    await example_tracing()
    await example_multi_provider()


if __name__ == "__main__":
    asyncio.run(main())
