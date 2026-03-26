# chatbot-evals SDK

Open-source Python SDK for evaluating enterprise chatbots. Like Galileo, MLflow Evals, and DeepEval - but free, open-source, and provider-agnostic.

## Install

```bash
pip install chatbot-evals
```

## Quick Start

```python
import asyncio
from chatbot_evals import ChatbotEvals, Conversation, Message

async def main():
    ce = ChatbotEvals(judge_model="gpt-4o-mini")

    report = await ce.evaluate_dataset(
        [
            Conversation(
                messages=[
                    Message(role="user", content="What is your return policy?"),
                    Message(role="assistant", content="Returns within 30 days with receipt."),
                ],
                context="Policy: 30 day returns, receipt required.",
            )
        ],
        metrics=["faithfulness", "relevance", "hallucination"],
    )

    print(report.metric_averages)
    report.to_html("report.html")

asyncio.run(main())
```

## Metrics

| Metric | Description |
|--------|-------------|
| `faithfulness` | Is the response grounded in provided context? |
| `relevance` | Does the response answer the user's question? |
| `hallucination` | Does the response contain fabricated information? |
| `toxicity` | Is the response free from harmful content? |
| `coherence` | Is the response logically structured? |
| `completeness` | Does it fully address the query? |
| `context_adherence` | Does the chatbot stay within its knowledge boundary? |
| `conversation_quality` | Multi-turn coherence and topic tracking |
| `latency` | Response time statistics |
| `cost` | Token usage and estimated cost |

## Custom Metrics

```python
from chatbot_evals.metrics.custom import custom_metric, llm_metric

@custom_metric(name="response_length")
async def response_length(conversation):
    words = conversation.messages[-1].content.split()
    return min(len(words) / 50, 1.0)

@llm_metric(name="empathy", prompt="Rate empathy 0-1: {response}")
def empathy():
    pass

report = await evaluate(conversations, metrics=["faithfulness", "response_length", "empathy"])
```

## Load Data

```python
from chatbot_evals.datasets import DatasetLoader

# From files
convs = DatasetLoader.from_json("data.json")
convs = DatasetLoader.from_csv("data.csv", mapping={"user_col": "q", "assistant_col": "a"})
convs = DatasetLoader.from_jsonl("data.jsonl")
```

## Integrations

```python
# Auto-trace OpenAI calls
from chatbot_evals.integrations import OpenAIWrapper
traced = OpenAIWrapper(openai_client, metrics=["faithfulness"])

# Auto-trace Anthropic calls
from chatbot_evals.integrations import AnthropicWrapper
traced = AnthropicWrapper(anthropic_client, metrics=["toxicity"])

# LangChain callback
from chatbot_evals.integrations import ChatbotEvalsCallbackHandler
handler = ChatbotEvalsCallbackHandler(metrics=["coherence"])
```

## Multi-Provider Judges

Use any LLM as the evaluation judge:

```python
# OpenAI
ce = ChatbotEvals(judge_model="gpt-4o")

# Claude
ce = ChatbotEvals(judge_model="claude-sonnet-4-20250514")

# Gemini
ce = ChatbotEvals(judge_model="gemini-2.0-flash")
```

## License

MIT
