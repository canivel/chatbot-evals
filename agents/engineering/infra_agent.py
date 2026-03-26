"""Infrastructure engineer agent for the multi-agent development team.

Specializes in Docker, CI/CD pipelines, deployment configurations,
monitoring setup, and production readiness.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.engineering.code_generator import CodeBlock, CodeGenerator, Language
from agents.engineering.prompts import INFRA_PROMPT
from agents.message_bus import Message, MessageBus, MessageType
from agents.state import ProjectState, StoryStatus, TaskType

logger = structlog.get_logger()


class InfraAgent(BaseAgent):
    """Infrastructure engineer agent.

    Handles:
    - Dockerfile generation (multi-stage, optimized)
    - Docker Compose configurations for dev/staging/prod
    - GitHub Actions CI/CD pipeline definitions
    - Monitoring and alerting configuration (Prometheus, Grafana)
    - Nginx reverse proxy and load balancing configs
    - Health checks and production readiness
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBus,
        project_state: ProjectState,
    ) -> None:
        if not config.system_prompt:
            config = config.model_copy(update={"system_prompt": INFRA_PROMPT})
        super().__init__(config, message_bus, project_state)
        self.code_gen = CodeGenerator(
            model=config.model,
            temperature=0.3,
            max_tokens=config.max_tokens,
        )

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def _get_responsibilities(self) -> str:
        return (
            "- Create optimized Dockerfiles for all services\n"
            "- Design docker-compose configurations (dev, staging, prod)\n"
            "- Build GitHub Actions CI/CD pipelines\n"
            "- Configure monitoring with Prometheus and Grafana\n"
            "- Set up Nginx reverse proxy and TLS termination\n"
            "- Ensure production readiness (health checks, logging, limits)"
        )

    async def process_message(self, message: Message) -> list[Message]:
        """Process an incoming message and return response messages."""
        responses: list[Message] = []

        logger.info(
            "infra_processing_message",
            agent_id=self.agent_id,
            message_type=message.message_type.value,
            subject=message.subject,
        )

        if message.message_type == MessageType.STORY:
            responses.extend(await self._handle_story(message))

        elif message.message_type == MessageType.TASK:
            responses.extend(await self._handle_task(message))

        elif message.message_type == MessageType.BUG_REPORT:
            responses.extend(await self._handle_bug(message))

        elif message.message_type == MessageType.REVIEW_REQUEST:
            responses.extend(await self._handle_review_request(message))

        elif message.message_type == MessageType.QUERY:
            responses.extend(await self._handle_query(message))

        return responses

    async def plan_work(self) -> list[dict[str, Any]]:
        """Plan the next unit of work from assigned stories and bugs."""
        tasks: list[dict[str, Any]] = []

        for story in self.state.stories.values():
            if (
                story.assigned_to == self.agent_id
                and story.status in (StoryStatus.READY, StoryStatus.IN_PROGRESS)
            ):
                tasks.append(
                    {
                        "type": "implement_story",
                        "story_id": story.id,
                        "title": story.title,
                        "description": story.description,
                        "task_type": story.task_type.value,
                    }
                )

        for bug in self.state.bugs.values():
            if (
                bug.assigned_to == self.agent_id
                and bug.status not in (StoryStatus.DONE, StoryStatus.IN_REVIEW)
            ):
                tasks.append(
                    {
                        "type": "fix_bug",
                        "bug_id": bug.id,
                        "title": bug.title,
                        "description": bug.description,
                    }
                )

        if tasks:
            logger.info(
                "infra_planned_work",
                agent_id=self.agent_id,
                task_count=len(tasks),
            )

        return tasks

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a planned task and return the result."""
        task_type = task.get("type", "")

        logger.info(
            "infra_executing_task",
            agent_id=self.agent_id,
            task_type=task_type,
            title=task.get("title", ""),
        )

        try:
            if task_type == "implement_story":
                return await self._implement_story(task)
            elif task_type == "fix_bug":
                return await self._fix_bug(task)
            elif task_type == "generate_dockerfile":
                return await self._generate_dockerfile(task)
            elif task_type == "generate_compose":
                return await self._generate_compose(task)
            elif task_type == "generate_ci_pipeline":
                return await self._generate_ci_pipeline(task)
            elif task_type == "generate_nginx_config":
                return await self._generate_nginx_config(task)
            elif task_type == "generate_monitoring":
                return await self._generate_monitoring(task)
            else:
                logger.warning("infra_unknown_task_type", task_type=task_type)
                return {"status": "error", "reason": f"Unknown task type: {task_type}"}
        except Exception as e:
            logger.error(
                "infra_task_failed",
                agent_id=self.agent_id,
                task_type=task_type,
                error=str(e),
            )
            return {"status": "error", "reason": str(e)}

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_story(self, message: Message) -> list[Message]:
        """Accept a story assignment and acknowledge."""
        story_id = message.payload.get("story_id", "")
        if story_id and story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_PROGRESS)
            self.state.assign_story(story_id, self.agent_id, "engineering")

        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.STATUS_UPDATE,
                subject=f"Accepted story: {message.subject}",
                payload={"story_id": story_id, "status": "in_progress"},
                reply_to=message.id,
            )
        ]

    async def _handle_task(self, message: Message) -> list[Message]:
        """Handle an ad-hoc task request."""
        result = await self.execute_task(message.payload)
        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.COMPLETION,
                subject=f"Completed: {message.subject}",
                payload=result,
                reply_to=message.id,
            )
        ]

    async def _handle_bug(self, message: Message) -> list[Message]:
        """Acknowledge and begin investigating an infra bug."""
        bug_id = message.payload.get("bug_id", "")
        if bug_id and bug_id in self.state.bugs:
            self.state.bugs[bug_id].assigned_to = self.agent_id
            self.state.bugs[bug_id].status = StoryStatus.IN_PROGRESS

        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.STATUS_UPDATE,
                subject=f"Investigating bug: {message.subject}",
                payload={"bug_id": bug_id, "status": "investigating"},
                reply_to=message.id,
            )
        ]

    async def _handle_review_request(self, message: Message) -> list[Message]:
        """Review infrastructure code submitted by another agent."""
        code = message.payload.get("code", "")
        language_str = message.payload.get("language", "yaml")
        context = message.payload.get("context", "")

        try:
            language = Language(language_str)
        except ValueError:
            language = Language.YAML

        review = await self.code_gen.review_code(code, language, context)

        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.REVIEW_RESULT,
                subject=f"Review: {message.subject}",
                payload={
                    "approved": review.approved,
                    "score": review.score,
                    "issues": review.issues,
                    "summary": review.summary,
                },
                reply_to=message.id,
            )
        ]

    async def _handle_query(self, message: Message) -> list[Message]:
        """Answer a technical question using the LLM."""
        question = message.payload.get("question", message.subject)
        answer = await self.call_llm(
            [{"role": "user", "content": question}],
            temperature=0.3,
        )

        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.RESPONSE,
                subject=f"Re: {message.subject}",
                payload={"answer": answer},
                reply_to=message.id,
            )
        ]

    # ------------------------------------------------------------------
    # Task execution helpers
    # ------------------------------------------------------------------

    async def _implement_story(self, task: dict[str, Any]) -> dict[str, Any]:
        """Implement a full infrastructure story."""
        story_id = task["story_id"]
        description = task["description"]

        plan_response = await self.call_llm(
            [
                {
                    "role": "user",
                    "content": (
                        f"Break down this infrastructure story into implementation steps.\n\n"
                        f"Story: {task['title']}\n"
                        f"Description: {description}\n\n"
                        "Return a JSON object with:\n"
                        '  "steps": [list of step descriptions],\n'
                        '  "dockerfiles": [list of Dockerfiles to create],\n'
                        '  "compose_files": [list of docker-compose files],\n'
                        '  "ci_pipelines": [list of CI/CD pipeline files],\n'
                        '  "config_files": [list of other config files]'
                    ),
                }
            ],
            json_mode=True,
            temperature=0.3,
        )

        try:
            plan = json.loads(plan_response)
        except json.JSONDecodeError:
            plan = {
                "steps": [description],
                "dockerfiles": [],
                "compose_files": [],
                "ci_pipelines": [],
                "config_files": [],
            }

        artifacts: dict[str, str] = {}

        # Generate Dockerfiles
        for dockerfile in plan.get("dockerfiles", []):
            block = await self.code_gen.generate_dockerfile(
                task_description=f"Create Dockerfile: {dockerfile}",
                requirements=description,
                filename=dockerfile,
                extra_context=f"Implementation plan:\n{json.dumps(plan, indent=2)}",
            )
            artifact_key = f"{story_id}/docker/{dockerfile}"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

        # Generate docker-compose files
        for compose_file in plan.get("compose_files", []):
            block = await self.code_gen.generate_yaml(
                task_description=f"Create docker-compose config: {compose_file}",
                requirements=description,
                filename=compose_file,
                extra_context=f"Implementation plan:\n{json.dumps(plan, indent=2)}",
            )
            artifact_key = f"{story_id}/compose/{compose_file}"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

        # Generate CI/CD pipelines
        for pipeline in plan.get("ci_pipelines", []):
            block = await self.code_gen.generate_yaml(
                task_description=f"Create GitHub Actions workflow: {pipeline}",
                requirements=description,
                filename=f".github/workflows/{pipeline}",
                extra_context=(
                    "Include:\n"
                    "- Trigger on push and pull_request\n"
                    "- Linting, type checking, and testing steps\n"
                    "- Docker build and push (if applicable)\n"
                    "- Proper caching for dependencies"
                ),
            )
            artifact_key = f"{story_id}/ci/{pipeline}"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

        # Generate other config files
        for config_file in plan.get("config_files", []):
            # Determine the right generator based on file extension
            if config_file.endswith(".py"):
                block = await self.code_gen.generate_python(
                    task_description=f"Create config: {config_file}",
                    requirements=description,
                    filename=config_file,
                )
            else:
                block = await self.code_gen.generate_yaml(
                    task_description=f"Create config: {config_file}",
                    requirements=description,
                    filename=config_file,
                )
            artifact_key = f"{story_id}/config/{config_file}"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

        if story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_REVIEW)

        await self.send_message(
            to_team="engineering",
            message_type=MessageType.REVIEW_REQUEST,
            subject=f"Review: {task['title']}",
            payload={
                "story_id": story_id,
                "artifacts": list(artifacts.keys()),
                "plan": plan,
            },
        )

        return {
            "status": "completed",
            "story_id": story_id,
            "artifacts": list(artifacts.keys()),
            "plan": plan,
        }

    async def _fix_bug(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a fix for an infrastructure bug."""
        bug_id = task["bug_id"]

        fix_response = await self.call_llm(
            [
                {
                    "role": "user",
                    "content": (
                        f"Diagnose and propose a fix for this infrastructure bug.\n\n"
                        f"Bug: {task['title']}\n"
                        f"Description: {task['description']}\n\n"
                        "Return a JSON object with:\n"
                        '  "diagnosis": "root cause analysis",\n'
                        '  "fix_description": "what needs to change",\n'
                        '  "affected_services": ["list of affected services"],\n'
                        '  "requires_restart": true/false,\n'
                        '  "files_to_modify": ["list of files"]'
                    ),
                }
            ],
            json_mode=True,
            temperature=0.3,
        )

        try:
            diagnosis = json.loads(fix_response)
        except json.JSONDecodeError:
            diagnosis = {
                "diagnosis": "Unable to parse diagnosis",
                "fix_description": task["description"],
                "affected_services": [],
                "requires_restart": False,
                "files_to_modify": [],
            }

        # Generate fix -- determine type based on files affected
        files_to_modify = diagnosis.get("files_to_modify", [])
        is_docker = any(
            "docker" in f.lower() or "Dockerfile" in f
            for f in files_to_modify
        )
        is_yaml = any(f.endswith((".yml", ".yaml")) for f in files_to_modify)

        if is_docker:
            fix_block = await self.code_gen.generate_dockerfile(
                task_description=f"Fix infrastructure bug: {task['title']}",
                requirements=diagnosis.get("fix_description", task["description"]),
            )
        elif is_yaml:
            fix_block = await self.code_gen.generate_yaml(
                task_description=f"Fix infrastructure bug: {task['title']}",
                requirements=diagnosis.get("fix_description", task["description"]),
            )
        else:
            fix_block = await self.code_gen.generate_python(
                task_description=f"Fix infrastructure bug: {task['title']}",
                requirements=diagnosis.get("fix_description", task["description"]),
            )

        artifact_key = f"{bug_id}/fix"
        self.state.artifacts[artifact_key] = fix_block.code

        if bug_id in self.state.bugs:
            self.state.bugs[bug_id].status = StoryStatus.IN_REVIEW

        return {
            "status": "fix_proposed",
            "bug_id": bug_id,
            "diagnosis": diagnosis,
            "artifact_key": artifact_key,
            "valid": fix_block.is_valid,
        }

    async def _generate_dockerfile(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a Dockerfile for a specific service."""
        service_name = task.get("service_name", "app")
        base_image = task.get("base_image", "python:3.12-slim")
        description = task.get("description", f"Dockerfile for {service_name}")

        block = await self.code_gen.generate_dockerfile(
            task_description=f"Create production Dockerfile for '{service_name}'",
            requirements=description,
            filename=f"docker/{service_name}/Dockerfile",
            extra_context=(
                f"Base image: {base_image}\n"
                "Requirements:\n"
                "- Multi-stage build (builder + runtime)\n"
                "- Non-root user for runtime\n"
                "- Proper COPY ordering for layer caching\n"
                "- Health check instruction\n"
                "- Minimal final image size"
            ),
        )

        artifact_key = f"docker/{service_name}/Dockerfile"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _generate_compose(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a docker-compose configuration."""
        environment = task.get("environment", "development")
        services = task.get("services", ["api", "frontend", "postgres", "redis"])
        description = task.get("description", f"Docker Compose for {environment}")

        services_str = "\n".join(f"- {s}" for s in services)

        block = await self.code_gen.generate_yaml(
            task_description=f"Create docker-compose.{environment}.yml",
            requirements=f"{description}\n\nServices:\n{services_str}",
            filename=f"docker-compose.{environment}.yml",
            extra_context=(
                "Include:\n"
                "- Named volumes for persistent data\n"
                "- Internal network for service communication\n"
                "- Environment variable configuration\n"
                "- Health checks for all services\n"
                "- Resource limits (memory, CPU)\n"
                "- Restart policies\n"
                "- Proper depends_on with condition: service_healthy"
            ),
        )

        artifact_key = f"docker-compose.{environment}.yml"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _generate_ci_pipeline(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a GitHub Actions CI/CD pipeline."""
        pipeline_name = task.get("pipeline_name", "ci")
        triggers = task.get("triggers", ["push", "pull_request"])
        stages = task.get("stages", ["lint", "test", "build", "deploy"])
        description = task.get("description", f"CI/CD pipeline: {pipeline_name}")

        triggers_str = ", ".join(triggers)
        stages_str = "\n".join(f"- {s}" for s in stages)

        block = await self.code_gen.generate_yaml(
            task_description=f"Create GitHub Actions workflow '{pipeline_name}'",
            requirements=(
                f"{description}\n"
                f"Triggers: {triggers_str}\n"
                f"Stages:\n{stages_str}"
            ),
            filename=f".github/workflows/{pipeline_name}.yml",
            extra_context=(
                "Include:\n"
                "- Dependency caching (pip, npm)\n"
                "- Matrix strategy for multiple Python/Node versions if applicable\n"
                "- Proper job dependencies and conditions\n"
                "- Artifact upload for test reports\n"
                "- Secrets handling for deployment credentials\n"
                "- Concurrency control to cancel outdated runs"
            ),
        )

        artifact_key = f".github/workflows/{pipeline_name}.yml"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _generate_nginx_config(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate an Nginx reverse proxy configuration."""
        upstream_services = task.get("upstream_services", {"api": 8000, "frontend": 3000})
        domain = task.get("domain", "evals.example.com")
        description = task.get("description", f"Nginx config for {domain}")

        upstreams_str = "\n".join(
            f"- {name}: port {port}" for name, port in upstream_services.items()
        )

        block = await self.code_gen.generate(
            task_description=f"Create Nginx reverse proxy configuration for '{domain}'",
            language=Language.SHELL,
            requirements=(
                f"{description}\n"
                f"Domain: {domain}\n"
                f"Upstream services:\n{upstreams_str}"
            ),
            tech_stack="Nginx",
            filename="nginx/nginx.conf",
            extra_context=(
                "Include:\n"
                "- Upstream blocks for each service\n"
                "- SSL/TLS configuration (placeholder cert paths)\n"
                "- Gzip compression\n"
                "- Security headers (X-Frame-Options, CSP, etc.)\n"
                "- Rate limiting\n"
                "- Access and error log configuration\n"
                "- WebSocket support for /ws paths"
            ),
        )

        artifact_key = "nginx/nginx.conf"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _generate_monitoring(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate monitoring configuration (Prometheus + Grafana)."""
        services = task.get("services", ["api", "postgres", "redis"])
        description = task.get("description", "Monitoring setup")

        artifacts: dict[str, str] = {}

        # Prometheus config
        prom_block = await self.code_gen.generate_yaml(
            task_description="Create Prometheus configuration",
            requirements=(
                f"{description}\n"
                f"Services to monitor: {', '.join(services)}\n"
                "Include scrape configs for all services."
            ),
            filename="monitoring/prometheus.yml",
            extra_context=(
                "Include:\n"
                "- Global scrape interval\n"
                "- Scrape configs for each service\n"
                "- Alerting rules file reference\n"
                "- Static and service discovery targets"
            ),
        )
        artifacts["monitoring/prometheus.yml"] = prom_block.code
        self.state.artifacts["monitoring/prometheus.yml"] = prom_block.code

        # Alert rules
        alert_block = await self.code_gen.generate_yaml(
            task_description="Create Prometheus alert rules",
            requirements=(
                f"Alert rules for services: {', '.join(services)}\n"
                "Cover: high error rate, high latency, service down, disk usage."
            ),
            filename="monitoring/alert_rules.yml",
        )
        artifacts["monitoring/alert_rules.yml"] = alert_block.code
        self.state.artifacts["monitoring/alert_rules.yml"] = alert_block.code

        return {
            "status": "generated",
            "artifacts": list(artifacts.keys()),
            "valid": all(
                self.code_gen._validate(code, Language.YAML) == []
                for code in artifacts.values()
            ),
        }
