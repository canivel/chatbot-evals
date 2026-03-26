# Evaluation Metrics

Documentation for all evaluation metrics in the Chatbot Evals Platform.

## Overview

The platform includes 10 built-in metrics plus support for custom metrics. Metrics fall into three types:

| Type | How it works | Examples |
|------|-------------|---------|
| **LLM-as-Judge** | Sends a structured prompt to an LLM and parses the JSON verdict | Faithfulness, Relevance, Hallucination, Toxicity, Coherence, Completeness, Context Adherence, Conversation Quality |
| **Computation-based** | Calculates scores from metadata without LLM calls | Latency, Cost |
| **Custom** | User-defined function or LLM prompt template | Any domain-specific check |

All metrics:
- Implement the `BaseMetric` interface
- Return scores normalized to **0.0 - 1.0** (higher is better)
- Are registered with the singleton `MetricRegistry`
- Can run concurrently within the `EvalEngine`

## Metric Categories

Metrics are organized into categories via the `MetricCategory` enum:

| Category | Description | Metrics |
|----------|-------------|---------|
| `FAITHFULNESS` | Grounding and factual accuracy | Faithfulness, Hallucination |
| `RELEVANCE` | How well responses address queries | Relevance |
| `SAFETY` | Harmful content detection | Toxicity |
| `QUALITY` | Response structure and completeness | Coherence, Completeness, Context Adherence, Conversation Quality |
| `PERFORMANCE` | Response time | Latency |
| `COST` | Token usage and cost | Cost |
| `CUSTOM` | User-defined metrics | Any custom metric |

---

## Built-in Metrics

### Faithfulness

**Module:** `evalplatform/eval_engine/metrics/faithfulness.py`
**Class:** `FaithfulnessMetric`
**Category:** `FAITHFULNESS`

**Description:**
Evaluates whether the chatbot's response is grounded in the provided context. Measures factual alignment between the response and source documents.

**How it works:**
1. Extracts distinct factual claims from the assistant's response.
2. Checks each claim against the retrieved context documents.
3. Classifies each claim as `supported`, `contradicted`, or `not_mentioned`.
4. Computes: `score = supported_claims / total_claims`.

**Scoring:**
- `1.0` -- Every claim in the response is supported by the context.
- `0.0` -- No claims are supported (or no context is provided).
- Returns `0.0` with an explanation if no retrieved context is available.

**When to use:**
- RAG (Retrieval-Augmented Generation) systems where responses must be grounded.
- Enterprise chatbots that must only answer based on approved knowledge bases.
- Any system where factual accuracy relative to source material matters.

**Example result details:**
```json
{
  "claims": [
    {"claim": "Returns accepted within 30 days", "verdict": "supported"},
    {"claim": "Refunds take 5-7 business days", "verdict": "supported"}
  ],
  "total_claims": 2,
  "supported_claims": 2,
  "contradicted_claims": 0,
  "not_mentioned_claims": 0,
  "confidence": 0.92
}
```

**Requires:** `retrieved_context` in `EvalContext`.

---

### Relevance

**Module:** `evalplatform/eval_engine/metrics/relevance.py`
**Class:** `RelevanceMetric`
**Category:** `RELEVANCE`

**Description:**
Evaluates whether the chatbot's response actually answers the user's question rather than providing off-topic or tangential information.

**How it works:**
1. The LLM judge generates hypothetical questions that the response would perfectly answer.
2. Assesses how well those hypothetical questions align with the actual user question.
3. Evaluates whether the response directly and completely addresses the question.

**Scoring:**
- `1.0` -- Response directly and completely answers the question.
- `0.0` -- Response is entirely off-topic or fails to address the question.
- Returns `0.0` if either the user message or assistant response is missing.

**When to use:**
- Customer support chatbots where users expect direct answers.
- FAQ systems where responses should match the intent of the question.
- Any system where relevance to the user's query is a key quality dimension.

**Example result details:**
```json
{
  "hypothetical_questions": [
    "What is the company's return policy?",
    "How long do I have to return an item?"
  ],
  "alignment_reasoning": "The hypothetical questions closely match the actual query.",
  "addresses_question": true,
  "completeness": "The response covers all aspects of the return policy.",
  "confidence": 0.88
}
```

---

### Hallucination

**Module:** `evalplatform/eval_engine/metrics/hallucination.py`
**Class:** `HallucinationMetric`
**Category:** `FAITHFULNESS`

**Description:**
Detects fabricated information in the chatbot's response -- facts, figures, claims, or entities that are not present in the provided context or common knowledge.

**How it works:**
1. Extracts all factual claims from the response.
2. Checks each claim against the provided context and common knowledge.
3. Flags claims as hallucinated with severity levels (low, medium, high).
4. Computes: `score = 1 - (hallucinated_claims / total_claims)`.

**Scoring:**
- `1.0` -- No hallucinations detected.
- `0.0` -- Every claim is hallucinated.
- Returns `1.0` if there is no assistant response (nothing to check).

**When to use:**
- Any chatbot where generating false information is harmful (healthcare, legal, finance).
- RAG systems to detect when the model generates beyond the context.
- Quality monitoring to track hallucination rates over time.

**Example result details:**
```json
{
  "claims": [
    {"claim": "20% off sale", "is_hallucinated": true, "severity": "high", "reason": "No sale mentioned in context"},
    {"claim": "Code SAVE20", "is_hallucinated": true, "severity": "high", "reason": "No discount code in context"}
  ],
  "total_claims": 4,
  "hallucinated_claims": 2,
  "hallucinated_statements": [
    {"claim": "20% off sale", "reason": "No sale mentioned in context", "severity": "high"}
  ],
  "severity_breakdown": {"low": 0, "medium": 0, "high": 2},
  "confidence": 0.95
}
```

---

### Toxicity

**Module:** `evalplatform/eval_engine/metrics/toxicity.py`
**Class:** `ToxicityMetric`
**Category:** `SAFETY`

**Description:**
Evaluates the safety of chatbot responses across multiple harm dimensions.

**How it works:**
1. Scans the response against 6 safety categories:
   - **Hate speech** -- Content targeting protected groups
   - **Harassment** -- Personal attacks, bullying, intimidation
   - **Sexual content** -- Explicit or suggestive material
   - **Violence** -- Graphic violence or promotion of violent acts
   - **Self-harm** -- Content encouraging self-harm
   - **Dangerous content** -- Instructions for illegal or dangerous activities
2. The LLM judge evaluates each dimension and assigns per-category scores.
3. The overall score is derived from the worst category.

**Scoring:**
- `1.0` -- Response is completely safe across all dimensions.
- `0.0` -- Severe safety violations detected.

**When to use:**
- Every production chatbot should include toxicity monitoring.
- Compliance requirements (especially in regulated industries).
- Detecting adversarial attacks that cause unsafe outputs.

---

### Coherence

**Module:** `evalplatform/eval_engine/metrics/coherence.py`
**Class:** `CoherenceMetric`
**Category:** `QUALITY`

**Description:**
Evaluates the logical structure, flow, and internal consistency of the chatbot's response.

**How it works:**
Assesses 5 dimensions via LLM judge:
1. **Logical flow** -- Ideas follow a logical sequence.
2. **Internal consistency** -- No self-contradictions.
3. **Clarity** -- Language is clear and understandable.
4. **Completeness of thought** -- Ideas are fully developed.
5. **Structure** -- Response is well-organized.

The overall score is a weighted average of the dimension scores.

**Scoring:**
- `1.0` -- Response is perfectly structured, clear, and consistent.
- `0.0` -- Response is incoherent, contradictory, or incomprehensible.

**When to use:**
- Evaluating long-form responses where structure matters.
- Detecting degradation in response quality.
- Comparing chatbot versions for response quality improvements.

---

### Completeness

**Module:** `evalplatform/eval_engine/metrics/completeness.py`
**Class:** `CompletenessMetric`
**Category:** `QUALITY`

**Description:**
Evaluates whether the chatbot's response fully addresses all aspects of the user's query, identifying missed topics or partial answers.

**How it works:**
1. Identifies every distinct topic, sub-question, or aspect in the user's question.
2. For each aspect, determines whether the response addresses it: `full`, `partial`, or `missing`.
3. Identifies important topics the response missed entirely.
4. Computes the score based on aspect coverage.

**Scoring:**
- `1.0` -- Every aspect of the question is fully addressed.
- `0.0` -- No aspects of the question are addressed.

**When to use:**
- Multi-part questions where partial answers are common.
- Customer support where incomplete answers lead to follow-up contacts.
- Any scenario where thoroughness is important.

---

### Context Adherence

**Module:** `evalplatform/eval_engine/metrics/context_adherence.py`
**Class:** `ContextAdherenceMetric`
**Category:** `QUALITY`

**Description:**
Checks whether the chatbot stays within its knowledge boundary and does not answer questions it should not -- critical for enterprise chatbots with specific scopes.

**How it works:**
1. Evaluates whether the chatbot only uses information from provided context and system prompt.
2. Checks if it appropriately declines out-of-scope questions.
3. Detects assumptions beyond what the context supports.
4. Verifies the chatbot stays within its defined role.

**Scoring:**
- `1.0` -- Response perfectly adheres to available context and role boundaries.
- `0.0` -- Response entirely ignores boundaries, answers out-of-scope questions freely.

**When to use:**
- Enterprise chatbots with defined scopes (e.g., only answer about Product X).
- Legal or compliance contexts where going beyond approved information is risky.
- Any system with explicit system prompts defining boundaries.

**Requires:** `system_prompt` and `retrieved_context` in `EvalContext` for best results.

---

### Conversation Quality

**Module:** `evalplatform/eval_engine/metrics/conversation_quality.py`
**Class:** `ConversationQualityMetric`
**Category:** `QUALITY`

**Description:**
Evaluates quality across the full multi-turn conversation rather than just the last Q/A pair. This metric is unique because it assesses the entire conversation flow.

**How it works:**
Evaluates 4 dimensions across all turns:
1. **Topic consistency** -- Does the chatbot stay on topic or drift?
2. **Context retention** -- Does it remember and use information from earlier turns?
3. **Escalation handling** -- How does it handle frustrated users or out-of-scope requests?
4. **Overall flow** -- Does the conversation feel natural and productive?

Also provides per-turn quality scores.

**Scoring:**
- `1.0` -- Excellent multi-turn coherence, context retention, and flow.
- `0.0` -- Conversation is disjointed, forgets context, and handles escalation poorly.

**When to use:**
- Multi-turn support conversations.
- Chatbots where context retention across turns is critical.
- Evaluating the overall user experience beyond individual responses.

---

### Latency

**Module:** `evalplatform/eval_engine/metrics/latency.py`
**Class:** `LatencyMetric`
**Category:** `PERFORMANCE`

**Description:**
Measures response time statistics and scores them against configurable thresholds. This is a **computation-based** metric that does not call an LLM.

**How it works:**
1. Reads `latency_seconds` values from conversation turn metadata.
2. Computes statistics (mean, p50, p95, max).
3. Scores against thresholds.

**Scoring thresholds:**

| Response Time | Score | Rating |
|---------------|-------|--------|
| < 1 second | 1.0 | Excellent |
| < 3 seconds | 0.8 | Good |
| < 5 seconds | 0.6 | Acceptable |
| < 10 seconds | 0.3 | Slow |
| >= 10 seconds | 0.1 | Very slow |

**When to use:**
- Real-time chatbots where response speed affects user experience.
- SLA monitoring.
- Performance regression detection.

**Requires:** `latency_seconds` in turn `metadata`.

---

### Cost

**Module:** `evalplatform/eval_engine/metrics/cost.py`
**Class:** `CostMetric`
**Category:** `COST`

**Description:**
Tracks token usage and estimated cost per conversation. This is a **computation-based** metric that does not call an LLM.

**How it works:**
1. Reads `input_tokens`, `output_tokens`, and `model` from turn metadata.
2. Looks up per-token pricing for the model.
3. Computes total cost and scores against thresholds.

**Built-in model pricing (per 1K tokens):**

| Model | Input | Output |
|-------|-------|--------|
| gpt-4o | $0.0025 | $0.0100 |
| gpt-4o-mini | $0.000150 | $0.000600 |
| gpt-4-turbo | $0.0100 | $0.0300 |
| claude-3-opus | $0.0150 | $0.0750 |
| claude-3-sonnet | $0.0030 | $0.0150 |
| claude-3-haiku | $0.00025 | $0.00125 |
| claude-3.5-sonnet | $0.0030 | $0.0150 |

**Scoring thresholds:**

| Cost per Conversation | Score | Rating |
|----------------------|-------|--------|
| < $0.01 | 1.0 | Excellent |
| < $0.05 | 0.8 | Good |
| < $0.15 | 0.6 | Acceptable |
| < $0.50 | 0.3 | Expensive |
| >= $0.50 | 0.1 | Very expensive |

**When to use:**
- Budget monitoring for LLM-powered chatbots.
- Comparing cost efficiency across models.
- Detecting cost anomalies (e.g., unexpectedly long responses).

**Requires:** `input_tokens`, `output_tokens`, and `model` in turn `metadata`.

---

## LLM-as-Judge

Most metrics use the `LLMJudge` class, which:

1. Sends a structured prompt to an LLM via OpenAI SDK.
2. Expects a JSON response with `score`, `reasoning`, `confidence`, and metric-specific fields.
3. Parses the response into a `JudgeVerdict` model.
4. Retries on transient failures (TimeoutError, ConnectionError, JSONDecodeError) using tenacity (exponential backoff, up to 3 attempts).

```python
class JudgeVerdict(BaseModel):
    score: float          # 0.0 to 1.0
    reasoning: str        # Explanation
    confidence: float     # 0.0 to 1.0
    raw_response: str     # Raw LLM output
    metadata: dict        # Metric-specific details
```

The judge model defaults to `gpt-4o` with `temperature=0.0` for deterministic evaluation.

### Prompt structure

Each metric defines a prompt template that includes:
- Role context for the judge
- The evaluation task description
- Input data (question, response, context)
- Output format specification (JSON schema)

The LLM returns structured JSON that is parsed into the verdict.

## Pairwise Comparison

The `PairwiseJudge` compares two chatbot responses for the same question:

```python
from evalplatform.eval_engine.judges.pairwise_judge import PairwiseJudge

judge = PairwiseJudge(model="gpt-4o")
result = await judge.compare(
    question="What are your hours?",
    response_a="We're open 9-5.",
    response_b="Our hours are Monday-Friday 9 AM to 5 PM EST, closed weekends.",
    context="Hours: Mon-Fri 9AM-5PM EST. Closed weekends.",
)

print(result.winner)      # "B"
print(result.score_a)     # 0.6
print(result.score_b)     # 0.9
print(result.reasoning)   # "Response B is more complete and specific..."
print(result.criteria_comparison)  # Per-criterion breakdown
```

**When to use:**
- A/B testing chatbot versions.
- Comparing model outputs.
- Ranking multiple response candidates.

Supports batch comparison via `compare_batch()` with concurrency control.

## Custom Metrics

### Option 1: Custom evaluation function

Wrap any async function as a metric:

```python
from evalplatform.eval_engine.metrics.custom import register_custom_metric
from evalplatform.eval_engine.metrics.base import EvalContext, MetricResult

async def check_greeting(ctx: EvalContext) -> MetricResult:
    response = ctx.last_assistant_message or ""
    has_greeting = any(
        word in response.lower()
        for word in ["hello", "hi", "hey", "welcome", "greetings"]
    )
    return MetricResult(
        metric_name="greeting_check",
        score=1.0 if has_greeting else 0.0,
        explanation="Greeting detected" if has_greeting else "No greeting found",
    )

metric = register_custom_metric(
    name="greeting_check",
    description="Checks if the response includes a greeting",
    eval_fn=check_greeting,
)
```

### Option 2: LLM-based custom metric

Define custom evaluation instructions for the LLM judge:

```python
from evalplatform.eval_engine.metrics.custom import register_llm_custom_metric

metric = register_llm_custom_metric(
    name="brand_voice",
    description="Checks consistency with brand voice guidelines",
    custom_instructions=(
        "Evaluate whether the response matches these brand voice guidelines:\n"
        "- Professional but friendly tone\n"
        "- Uses 'we' instead of 'I'\n"
        "- Avoids jargon\n"
        "- Includes a call to action\n\n"
        "Score 1.0 if all guidelines are followed, 0.0 if none are."
    ),
    model="gpt-4o",
)
```

The `LLMCustomMetric` automatically provides the question, response, context, ground truth, and system prompt to the judge via template placeholders.

### Custom metric template placeholders

When creating an `LLMCustomMetric`, the following data is automatically injected:

| Placeholder | Source |
|-------------|--------|
| `{question}` | Last user message from the conversation |
| `{response}` | Last assistant message from the conversation |
| `{context}` | Retrieved context documents (joined) |
| `{system_prompt}` | The chatbot's system prompt |
| `{ground_truth}` | The expected correct answer |

## Metric Registry

The `MetricRegistry` is a thread-safe singleton that manages all metrics:

```python
from evalplatform.eval_engine.registry import metric_registry

# List all registered metrics
metrics = metric_registry.list_metrics()
# [{"name": "faithfulness", "description": "...", "version": "1.0.0", "category": "faithfulness"}, ...]

# Get a specific metric instance
metric = metric_registry.get_metric("relevance")

# Get all metrics in a category
safety_metrics = metric_registry.get_metrics_by_category("safety")

# Check if a metric exists
assert "hallucination" in metric_registry

# Count registered metrics
print(len(metric_registry))  # 10+
```

### Registration

Metrics are registered in two ways:

1. **Decorator** (recommended for built-in metrics):
   ```python
   @metric_registry.register
   class MyMetric(BaseMetric):
       name = "my_metric"
       ...
   ```

2. **Runtime registration** (for custom metrics):
   ```python
   register_custom_metric(name="my_metric", description="...", eval_fn=my_fn)
   ```

Registration enforces:
- The class must be a subclass of `BaseMetric`.
- The `name` attribute must be unique (duplicate registration of the same class is allowed; different classes with the same name raise `ValueError`).

### Metric discovery

Metrics are discovered by import. The `evalplatform/eval_engine/metrics/__init__.py` module imports all built-in metrics, triggering registration. To use all metrics, simply:

```python
import evalplatform.eval_engine.metrics  # registers all 10 metrics
```

Or import individual metrics:

```python
from evalplatform.eval_engine.metrics.faithfulness import FaithfulnessMetric  # registers just this one
```

## Running Evaluations

### Using the EvalEngine

```python
from evalplatform.eval_engine.engine import EvalEngine, EvalConfig
import evalplatform.eval_engine.metrics  # register all metrics

engine = EvalEngine()

# Run specific metrics
config = EvalConfig(
    metric_names=["faithfulness", "relevance", "hallucination"],
    max_concurrency=10,
    fail_on_error=False,
)

# Run all registered metrics (empty metric_names list)
config = EvalConfig()

run = await engine.run_eval(conversations, config)
```

### EvalConfig options

| Field | Default | Description |
|-------|---------|-------------|
| `metric_names` | `[]` (all) | Specific metrics to run. Empty = all registered. |
| `max_concurrency` | `10` | Max concurrent metric evaluations per conversation. |
| `fail_on_error` | `False` | If True, raises on first error. If False, records errors and continues. |
| `metadata` | `{}` | Arbitrary run-level metadata. |

### EvalRun results

The `EvalRun` object contains:
- `conversation_results` -- Per-conversation metric results
- `aggregate_scores` -- Per-metric mean score across all conversations
- `overall_score` -- Grand mean of all metric scores
- `started_at` / `completed_at` -- Timing information

```python
print(f"Overall: {run.overall_score:.4f}")
for metric, score in run.aggregate_scores.items():
    print(f"  {metric}: {score:.4f}")
```
