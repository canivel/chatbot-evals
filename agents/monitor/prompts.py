"""Prompt templates for the Monitor Agent."""

MONITOR_SYSTEM_PROMPT = """You are the Project Monitor Agent for the Chatbot Evals Platform.
Your role is to continuously monitor project health, identify patterns and bottlenecks,
and provide actionable recommendations to the team.

You track:
- Sprint velocity trends
- Bug rates and patterns
- Team workload balance
- Eval metric coverage
- Overall project readiness

You communicate with:
- Product Manager: recommendations, escalations, process improvements
- Orchestrator: configuration changes, workload rebalancing
- All teams: health alerts, process updates
"""

SPRINT_ANALYSIS_PROMPT = """Analyze the following sprint metrics and provide recommendations.

Sprint {sprint_number} Results:
- Stories planned: {stories_planned}
- Stories completed: {stories_completed}
- Bugs found: {bugs_found}
- Bugs resolved: {bugs_resolved}

Historical velocity: {historical_velocity}

Provide:
1. Velocity assessment (improving/stable/declining)
2. Quality assessment (bug rate trend)
3. Top 3 risks
4. Top 3 recommendations for next sprint
5. Agent configuration changes (if any)

Respond in JSON format."""

HEALTH_CHECK_PROMPT = """Perform a project health check based on these metrics:

{metrics_json}

Recent activity:
{activity_json}

Assess:
1. Overall health score (0-100)
2. Critical issues requiring immediate attention
3. Areas performing well
4. Areas needing improvement
5. Process bottlenecks

Respond in JSON format."""

EVOLUTION_REPORT_PROMPT = """Generate a project evolution report.

Sprint history: {sprint_history}
Current metrics: {current_metrics}
Bug trends: {bug_trends}
Team performance: {team_performance}

Create a comprehensive report with:
1. Executive summary
2. Progress against milestones
3. Quality metrics trend
4. Team efficiency analysis
5. Risk register
6. Recommendations
7. Next sprint focus areas

Respond in JSON format."""

PATTERN_DETECTION_PROMPT = """Analyze the following bug reports for systemic patterns:

Bugs:
{bugs_json}

Stories affected:
{stories_json}

Identify:
1. Common root causes
2. Affected components/areas
3. Recurring patterns
4. Systemic issues vs one-off bugs
5. Recommendations for prevention

Respond in JSON format."""
