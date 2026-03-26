"""Base agent class for all agents in the multi-agent development team.

Provides LLM integration via LiteLLM, message bus connectivity,
state access, and a standard agent lifecycle.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

import structlog
from litellm import acompletion
from pydantic import BaseModel, Field

from agents.message_bus import Message, MessageBus, MessageType
from agents.state import ProjectState

logger = structlog.get_logger()


class AgentConfig(BaseModel):
    agent_id: str
    name: str
    role: str
    team: str
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 4096
    max_turns: int = 20
    system_prompt: str = ""


class AgentContext(BaseModel):
    """Context passed to an agent for each turn."""

    messages: list[Message] = Field(default_factory=list)
    current_task: dict[str, Any] | None = None
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)


class BaseAgent(ABC):
    """Base class for all agents in the development team.

    Provides:
    - LLM integration via LiteLLM (multi-provider)
    - Message bus connectivity for inter-agent communication
    - Access to shared project state
    - Standard lifecycle (initialize, process, act)
    - Conversation history management
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBus,
        project_state: ProjectState,
    ) -> None:
        self.config = config
        self.bus = message_bus
        self.state = project_state
        self.context = AgentContext()
        self._running = False
        self._turn_count = 0

        # Register with message bus
        self.bus.register_agent(self.config.agent_id, self.config.team)

        logger.info(
            "agent_initialized",
            agent_id=self.config.agent_id,
            role=self.config.role,
            team=self.config.team,
        )

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    @property
    def system_prompt(self) -> str:
        base = f"""You are {self.config.name}, a {self.config.role} on the {self.config.team} team.
You are part of a multi-agent development team building an open-source chatbot evaluation SaaS platform.

Your responsibilities:
{self._get_responsibilities()}

Communication protocol:
- You receive messages from other agents via the message bus
- You can send stories, tasks, bug reports, feature requests, and status updates
- Always reference story/bug IDs when communicating about specific items
- Be concise and actionable in your communications

Current project state:
- Sprint: {self.state.current_sprint.number}
- Open stories: {len([s for s in self.state.stories.values() if s.status.value not in ('done', 'backlog')])}
- Open bugs: {len(self.state.get_open_bugs())}
"""
        if self.config.system_prompt:
            base += f"\n\nAdditional context:\n{self.config.system_prompt}"
        return base

    @abstractmethod
    def _get_responsibilities(self) -> str:
        """Return a description of this agent's responsibilities."""

    @abstractmethod
    async def process_message(self, message: Message) -> list[Message]:
        """Process an incoming message and return response messages."""

    @abstractmethod
    async def plan_work(self) -> list[dict[str, Any]]:
        """Plan the next unit of work. Returns a list of planned actions."""

    @abstractmethod
    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a specific task. Returns the result."""

    async def call_llm(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """Call the LLM with the given messages."""
        full_messages = [
            {"role": "system", "content": self.system_prompt},
            *messages,
        ]

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": full_messages,
            "temperature": temperature or self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await acompletion(**kwargs)
            content = response.choices[0].message.content
            self.context.conversation_history.append({"role": "assistant", "content": content})
            self.state.log_activity(self.agent_id, "llm_call", {"model": self.config.model})
            return content
        except Exception as e:
            logger.error("llm_call_failed", agent_id=self.agent_id, error=str(e))
            raise

    async def send_message(
        self,
        to_agent: str | None = None,
        to_team: str | None = None,
        message_type: MessageType = MessageType.STATUS_UPDATE,
        subject: str = "",
        payload: dict[str, Any] | None = None,
        priority: str = "medium",
    ) -> None:
        """Send a message to another agent or team."""
        msg = Message(
            from_agent=self.agent_id,
            to_agent=to_agent,
            to_team=to_team,
            message_type=message_type,
            subject=subject,
            payload=payload or {},
            priority=priority,
        )
        await self.bus.send(msg)

    async def broadcast(
        self,
        message_type: MessageType,
        subject: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Broadcast a message to all agents."""
        await self.send_message(
            message_type=message_type,
            subject=subject,
            payload=payload,
        )

    async def run_turn(self) -> bool:
        """Execute one turn of the agent's main loop.

        Returns True if the agent should continue, False if done.
        """
        self._turn_count += 1
        if self._turn_count > self.config.max_turns:
            logger.info("agent_max_turns_reached", agent_id=self.agent_id)
            return False

        # 1. Check for incoming messages
        incoming = await self.bus.receive_all(self.agent_id)
        self.context.messages = incoming

        # 2. Process messages
        for msg in incoming:
            responses = await self.process_message(msg)
            for response in responses:
                await self.bus.send(response)

        # 3. Plan next work
        planned = await self.plan_work()

        # 4. Execute planned tasks
        for task in planned:
            result = await self.execute_task(task)
            self.state.log_activity(
                self.agent_id,
                "task_completed",
                {"task": task, "result": result},
            )

        return True

    async def run(self, max_turns: int | None = None) -> None:
        """Run the agent's main loop."""
        self._running = True
        turns = max_turns or self.config.max_turns

        logger.info("agent_started", agent_id=self.agent_id, max_turns=turns)

        for _ in range(turns):
            if not self._running:
                break
            try:
                should_continue = await self.run_turn()
                if not should_continue:
                    break
            except Exception as e:
                logger.error("agent_turn_error", agent_id=self.agent_id, error=str(e))
                await asyncio.sleep(1)

        self._running = False
        logger.info("agent_stopped", agent_id=self.agent_id, turns=self._turn_count)

    def stop(self) -> None:
        self._running = False
