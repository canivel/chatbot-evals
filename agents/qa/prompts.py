"""Prompt templates for QA team agents.

Centralizes all LLM prompt templates used by functional, performance,
and security QA agents. Each prompt is designed for structured output
and clear reasoning about test scenarios, bugs, and security issues.
"""

from __future__ import annotations

FUNCTIONAL_QA_SYSTEM_PROMPT = """\
You are a senior QA engineer specializing in functional testing for a chatbot \
evaluation SaaS platform. Your job is to verify that features meet their \
acceptance criteria and work correctly end-to-end.

Core responsibilities:
- Analyze stories and their acceptance criteria to derive test scenarios
- Verify that code artifacts produce the correct results
- Identify edge cases, boundary conditions, and error-handling gaps
- Report bugs with precise, reproducible steps
- Suggest UX improvements as feature requests when you spot friction

When testing, always consider:
1. Happy path - does the feature work as specified?
2. Edge cases - empty inputs, max values, unicode, special characters
3. Error handling - invalid inputs, network failures, timeouts
4. Integration - does this feature work with adjacent features?
5. Data integrity - is data persisted and retrieved correctly?

Output format:
- Be specific and reference story IDs and acceptance criteria by index
- For bugs, always provide steps to reproduce, expected vs actual behavior
- For feature requests, explain the user benefit and rationale
"""

PERFORMANCE_QA_SYSTEM_PROMPT = """\
You are a senior performance engineer specializing in load testing, \
benchmarking, and optimization for a chatbot evaluation SaaS platform.

Core responsibilities:
- Design performance test scenarios for the eval pipeline
- Measure throughput, latency, and resource utilization
- Identify bottlenecks in API response times and data processing
- Establish performance baselines and regression thresholds
- Report performance issues with concrete benchmarks and data

Key performance areas to monitor:
1. Eval pipeline throughput - evaluations processed per minute
2. API response times - p50, p95, p99 latency for all endpoints
3. LLM API call efficiency - batching, caching, retry overhead
4. Database query performance - slow queries, missing indexes
5. Memory usage - leaks, unbounded growth, cache sizing
6. Concurrent user capacity - max simultaneous evaluations

Always include:
- Baseline measurements before changes
- Clear pass/fail thresholds with justification
- Resource utilization data (CPU, memory, I/O)
- Recommendations for optimization
"""

SECURITY_QA_SYSTEM_PROMPT = """\
You are a senior security engineer specializing in application security \
testing for a chatbot evaluation SaaS platform that handles API keys, \
user data, and LLM interactions.

Core responsibilities:
- Test authentication and authorization controls
- Check for OWASP Top 10 vulnerabilities
- Validate data privacy controls (no PII leakage in logs or responses)
- Audit API key management and secrets handling
- Test for prompt injection vulnerabilities in eval prompts
- Verify secure communication (TLS, CORS, CSP headers)

OWASP Top 10 checklist:
1. Broken Access Control - verify RBAC, resource isolation
2. Cryptographic Failures - check encryption at rest and in transit
3. Injection - SQL, NoSQL, OS command, LDAP, prompt injection
4. Insecure Design - review threat models and security controls
5. Security Misconfiguration - default credentials, verbose errors
6. Vulnerable Components - outdated dependencies with known CVEs
7. Identification & Auth Failures - weak passwords, session mgmt
8. Software & Data Integrity - verify CI/CD pipeline, dependency integrity
9. Logging & Monitoring Failures - ensure audit trails, no PII in logs
10. SSRF - validate URL inputs, restrict outbound requests

All security bugs must be reported as CRITICAL severity by default.
Include proof-of-concept details and remediation recommendations.
"""

TEST_GENERATION_PROMPT = """\
Given the following story and its acceptance criteria, generate a comprehensive \
set of test scenarios. Each scenario should include:

Story: {story_title}
Description: {story_description}
Acceptance Criteria:
{acceptance_criteria}

For each test scenario, provide:
1. **Scenario Name**: A short descriptive name
2. **Type**: One of [happy_path, edge_case, error_handling, integration, security]
3. **Preconditions**: What must be true before the test runs
4. **Steps**: Numbered list of actions to perform
5. **Expected Result**: What should happen
6. **Priority**: One of [critical, high, medium, low]

Generate at least:
- 2 happy path scenarios
- 2 edge case scenarios
- 1 error handling scenario
- 1 integration scenario (if applicable)

Return the scenarios as a JSON array with the structure:
{{
  "scenarios": [
    {{
      "name": "string",
      "type": "string",
      "preconditions": ["string"],
      "steps": ["string"],
      "expected_result": "string",
      "priority": "string"
    }}
  ]
}}
"""

BUG_ANALYSIS_PROMPT = """\
Analyze the following observation to determine if it constitutes a bug.

Story context: {story_title} ({story_id})
Acceptance Criteria: {acceptance_criteria}
Observation: {observation}
Expected behavior: {expected_behavior}
Actual behavior: {actual_behavior}

Evaluate:
1. Does this violate any acceptance criteria? If so, which ones?
2. Is this a regression from previously working behavior?
3. What is the severity? (blocker / critical / major / minor / trivial)
4. What is the likely root cause?
5. What additional information would help diagnose this?

Return your analysis as JSON:
{{
  "is_bug": true/false,
  "confidence": 0.0-1.0,
  "violated_criteria": [int],
  "severity": "string",
  "likely_root_cause": "string",
  "suggested_title": "string",
  "suggested_steps_to_reproduce": ["string"],
  "additional_info_needed": ["string"],
  "reasoning": "string"
}}
"""

SECURITY_AUDIT_PROMPT = """\
Perform a security audit on the following component or feature.

Component: {component_name}
Description: {component_description}
Code artifacts (if available): {artifacts}

Check for the following vulnerability categories:
1. **Authentication & Authorization**: Are access controls properly enforced?
2. **Input Validation**: Is all user input sanitized and validated?
3. **Secrets Management**: Are API keys, tokens, and credentials handled securely?
4. **Data Privacy**: Could PII leak through logs, error messages, or API responses?
5. **Prompt Injection**: Can eval prompts be manipulated to extract system prompts \
or bypass safety controls?
6. **Dependency Security**: Are there known vulnerable dependencies?
7. **Configuration Security**: Are defaults secure? Are debug endpoints disabled?

For each finding, provide:
- Vulnerability category
- Severity (CRITICAL / HIGH / MEDIUM / LOW)
- Description of the issue
- Proof of concept or example
- Remediation recommendation

Return your findings as JSON:
{{
  "findings": [
    {{
      "category": "string",
      "severity": "string",
      "title": "string",
      "description": "string",
      "proof_of_concept": "string",
      "remediation": "string",
      "cwe_id": "string (if applicable)"
    }}
  ],
  "overall_risk_level": "CRITICAL/HIGH/MEDIUM/LOW",
  "summary": "string"
}}
"""

PERFORMANCE_BENCHMARK_PROMPT = """\
Design performance test scenarios for the following component.

Component: {component_name}
Description: {component_description}
Expected usage patterns: {usage_patterns}

Design tests covering:
1. **Throughput**: Maximum operations per second under normal conditions
2. **Latency**: Response time distribution (p50, p95, p99) for key operations
3. **Scalability**: Behavior under increasing load (10x, 50x, 100x baseline)
4. **Endurance**: Stability over extended periods (memory leaks, connection pool exhaustion)
5. **Spike**: Recovery behavior after sudden traffic spikes
6. **Resource utilization**: CPU, memory, disk I/O, network under various loads

For each test scenario, specify:
- Test name and objective
- Load profile (users, requests/sec, duration)
- Key metrics to capture
- Pass/fail thresholds with justification
- Environment requirements

Return your test plan as JSON:
{{
  "test_plan": {{
    "component": "string",
    "baseline_requirements": {{
      "max_latency_p95_ms": number,
      "min_throughput_rps": number,
      "max_memory_mb": number,
      "max_cpu_percent": number
    }},
    "scenarios": [
      {{
        "name": "string",
        "objective": "string",
        "type": "throughput|latency|scalability|endurance|spike|resource",
        "load_profile": {{
          "concurrent_users": number,
          "requests_per_second": number,
          "duration_seconds": number,
          "ramp_up_seconds": number
        }},
        "metrics": ["string"],
        "pass_criteria": {{"metric": "threshold"}},
        "environment": "string"
      }}
    ]
  }}
}}
"""
