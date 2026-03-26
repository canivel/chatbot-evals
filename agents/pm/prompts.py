"""Prompt templates for the Product Manager agent.

These templates are used to drive LLM calls for story generation,
bug triage, sprint planning, feature prioritization, and initial
backlog creation for the chatbot evaluation platform.
"""

from __future__ import annotations

STORY_GENERATION_PROMPT = """\
You are a senior product manager for an open-source chatbot evaluation SaaS platform.

Given the following high-level requirement, generate a detailed user story.

Requirement:
{requirement}

Area: {area}

Respond in JSON with exactly this schema:
{{
  "title": "<concise story title>",
  "description": "<detailed description in user-story format: As a [persona], I want [goal] so that [benefit]. Include technical context.>",
  "acceptance_criteria": [
    "<criterion 1>",
    "<criterion 2>",
    "<criterion 3>"
  ],
  "story_points": <integer 1-13 using fibonacci: 1, 2, 3, 5, 8, 13>,
  "priority": "<critical|high|medium|low>",
  "tags": ["<tag1>", "<tag2>"],
  "depends_on_areas": ["<area this depends on, if any>"]
}}

Guidelines:
- Write acceptance criteria that are specific, measurable, and testable.
- Story points should reflect complexity, not time.
- Tags should include the area ({area}) and any relevant technologies.
- Be specific about what "done" looks like.
"""

BUG_TRIAGE_PROMPT = """\
You are a senior product manager triaging a bug report for a chatbot evaluation SaaS platform.

Bug Report:
- Title: {title}
- Description: {description}
- Severity: {severity}
- Steps to Reproduce: {steps_to_reproduce}
- Expected Behavior: {expected_behavior}
- Actual Behavior: {actual_behavior}
- Environment: {environment}
- Related Story: {related_story}

Respond in JSON with exactly this schema:
{{
  "fix_story_title": "<concise title for the fix story>",
  "fix_story_description": "<detailed description of what needs to be fixed and how to approach it>",
  "acceptance_criteria": [
    "<criterion 1 - must verify the bug is fixed>",
    "<criterion 2 - regression test>",
    "<criterion 3>"
  ],
  "priority": "<critical|high|medium|low>",
  "story_points": <integer 1-13>,
  "tags": ["bug-fix", "<additional tags>"],
  "root_cause_hypothesis": "<brief hypothesis about the root cause>",
  "impact_assessment": "<who is affected and how severely>"
}}

Guidelines:
- Blocker and critical bugs should map to critical or high priority.
- Always include a regression-test acceptance criterion.
- The fix story should be actionable by a developer without further clarification.
"""

SPRINT_PLANNING_PROMPT = """\
You are a senior product manager planning the next sprint for a chatbot evaluation SaaS platform.

Team Capacity: {capacity} story points
Historical Velocity: {velocity} story points per sprint
Current Sprint: {sprint_number}

Backlog (ordered by priority):
{backlog_summary}

Open Bugs:
{bugs_summary}

Completed in Previous Sprint:
{completed_summary}

Respond in JSON with exactly this schema:
{{
  "sprint_goal": "<one-sentence sprint goal>",
  "selected_story_ids": ["<story_id_1>", "<story_id_2>"],
  "rationale": "<brief explanation of why these stories were selected>",
  "risks": ["<risk 1>", "<risk 2>"],
  "total_points": <sum of selected story points>,
  "stretch_story_ids": ["<optional stretch goal story ids>"]
}}

Guidelines:
- Do not exceed team capacity.
- Prioritize bug fixes and critical items.
- Respect story dependencies (don't schedule a story if its dependency isn't done or in the same sprint).
- Aim for a coherent sprint goal that ties the stories together.
- Include stretch goals only if they are small and low-risk.
"""

FEATURE_PRIORITIZATION_PROMPT = """\
You are a senior product manager evaluating a feature request for a chatbot evaluation SaaS platform.

Feature Request:
- Title: {title}
- Description: {description}
- Rationale: {rationale}
- Requested By: {requested_by}

Current Project Context:
- Open stories: {open_story_count}
- Current sprint focus: {sprint_goal}
- Existing backlog areas: {backlog_areas}

Respond in JSON with exactly this schema:
{{
  "recommended_priority": "<critical|high|medium|low>",
  "story_title": "<title for the story if we proceed>",
  "story_description": "<detailed description in user-story format>",
  "acceptance_criteria": [
    "<criterion 1>",
    "<criterion 2>"
  ],
  "story_points": <integer 1-13>,
  "tags": ["<tag1>", "<tag2>"],
  "reasoning": "<why this priority was assigned>",
  "schedule_recommendation": "<now|next_sprint|later|needs_research>",
  "dependencies": ["<dependency 1, if any>"]
}}

Guidelines:
- Consider strategic alignment with the chatbot eval platform mission.
- Weigh user impact vs. implementation effort.
- If the feature overlaps with existing backlog items, note that.
- "needs_research" means a spike story should be created first.
"""

INITIAL_BACKLOG_PROMPT = """\
You are a senior product manager creating the initial backlog for an open-source \
chatbot evaluation SaaS platform.

The platform needs to support:
1. Eval Engine - Running evaluation suites against chatbot APIs (LLM-as-judge, \
rule-based, human-in-the-loop scoring).
2. Connectors - Integrating with multiple LLM providers (OpenAI, Anthropic, Google, \
open-source models via Ollama/vLLM).
3. API Layer - RESTful + WebSocket API for running evals, managing datasets, and \
retrieving results.
4. Frontend - Dashboard for configuring evals, viewing results with charts, \
comparing model runs, and managing datasets.
5. Infrastructure - CI/CD, containerization, database schema, auth, observability.

Generate {story_count} user stories that form a coherent initial backlog. \
Cover all five areas proportionally.

Respond in JSON with exactly this schema:
{{
  "stories": [
    {{
      "title": "<concise title>",
      "description": "<user-story format description>",
      "acceptance_criteria": ["<ac1>", "<ac2>", "<ac3>"],
      "story_points": <1-13>,
      "priority": "<critical|high|medium|low>",
      "tags": ["<area>", "<tech-tags>"],
      "area": "<eval_engine|connectors|api|frontend|infra>",
      "depends_on_titles": ["<title of story this depends on, if any>"]
    }}
  ]
}}

Guidelines:
- Start with foundational infrastructure and API stories as high priority.
- Eval engine core is critical - it's the heart of the platform.
- Frontend stories should depend on API stories.
- Include stories for testing infrastructure and CI/CD.
- Each story should be independently deliverable.
- Use fibonacci story points (1, 2, 3, 5, 8, 13).
- Distribute across areas: ~25% eval engine, ~15% connectors, ~20% API, ~25% frontend, ~15% infra.
"""
