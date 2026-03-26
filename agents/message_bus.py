"""Inter-agent message bus for communication between agents.

Implements an async pub/sub message bus with typed messages,
routing, and message history tracking.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class MessageType(str, Enum):
    STORY = "story"
    TASK = "task"
    BUG_REPORT = "bug_report"
    FEATURE_REQUEST = "feature_request"
    REVIEW_REQUEST = "review_request"
    REVIEW_RESULT = "review_result"
    COMPLETION = "completion"
    STATUS_UPDATE = "status_update"
    SPRINT_EVENT = "sprint_event"
    QUERY = "query"
    RESPONSE = "response"
    BROADCAST = "broadcast"
    ESCALATION = "escalation"
    MONITOR_UPDATE = "monitor_update"


class Message(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    from_agent: str
    to_agent: str | None = None  # None = broadcast
    to_team: str | None = None
    message_type: MessageType
    subject: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    references: list[str] = Field(default_factory=list)
    priority: str = "medium"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reply_to: str | None = None
    requires_ack: bool = False
    acknowledged: bool = False


MessageHandler = Callable[[Message], Coroutine[Any, Any, Message | None]]


class MessageBus:
    """Async message bus for inter-agent communication.

    Supports:
    - Direct agent-to-agent messaging
    - Team-level messaging
    - Broadcast to all agents
    - Message history and replay
    - Priority-based ordering
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Message]] = {}
        self._team_members: dict[str, set[str]] = {}
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._history: list[Message] = []
        self._running = False

    def register_agent(self, agent_id: str, team: str | None = None) -> None:
        self._queues[agent_id] = asyncio.Queue()
        if team:
            if team not in self._team_members:
                self._team_members[team] = set()
            self._team_members[team].add(agent_id)
        logger.info("agent_registered", agent_id=agent_id, team=team)

    def unregister_agent(self, agent_id: str) -> None:
        self._queues.pop(agent_id, None)
        for team_members in self._team_members.values():
            team_members.discard(agent_id)

    def subscribe(self, agent_id: str, handler: MessageHandler) -> None:
        if agent_id not in self._handlers:
            self._handlers[agent_id] = []
        self._handlers[agent_id].append(handler)

    async def send(self, message: Message) -> None:
        self._history.append(message)

        if message.to_agent and message.to_agent in self._queues:
            await self._queues[message.to_agent].put(message)
            logger.info(
                "message_sent",
                from_agent=message.from_agent,
                to_agent=message.to_agent,
                type=message.message_type,
            )
        elif message.to_team and message.to_team in self._team_members:
            for member in self._team_members[message.to_team]:
                if member != message.from_agent:
                    await self._queues[member].put(message)
            logger.info(
                "team_message_sent",
                from_agent=message.from_agent,
                to_team=message.to_team,
                type=message.message_type,
            )
        elif not message.to_agent and not message.to_team:
            # Broadcast
            for agent_id, queue in self._queues.items():
                if agent_id != message.from_agent:
                    await queue.put(message)
            logger.info(
                "broadcast_sent",
                from_agent=message.from_agent,
                type=message.message_type,
            )

    async def receive(self, agent_id: str, timeout: float = 5.0) -> Message | None:
        if agent_id not in self._queues:
            return None
        try:
            return await asyncio.wait_for(self._queues[agent_id].get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def receive_all(self, agent_id: str) -> list[Message]:
        messages = []
        if agent_id not in self._queues:
            return messages
        while not self._queues[agent_id].empty():
            messages.append(self._queues[agent_id].get_nowait())
        return messages

    def get_history(
        self,
        agent_id: str | None = None,
        message_type: MessageType | None = None,
        limit: int = 50,
    ) -> list[Message]:
        history = self._history
        if agent_id:
            history = [
                m for m in history
                if m.from_agent == agent_id or m.to_agent == agent_id
            ]
        if message_type:
            history = [m for m in history if m.message_type == message_type]
        return history[-limit:]

    def get_pending_count(self, agent_id: str) -> int:
        if agent_id in self._queues:
            return self._queues[agent_id].qsize()
        return 0

    def get_team_members(self, team: str) -> set[str]:
        return self._team_members.get(team, set())

    async def acknowledge(self, message_id: str) -> None:
        for msg in reversed(self._history):
            if msg.id == message_id:
                msg.acknowledged = True
                break

    async def reply(self, original: Message, reply_payload: dict[str, Any], from_agent: str) -> None:
        reply_msg = Message(
            from_agent=from_agent,
            to_agent=original.from_agent,
            message_type=MessageType.RESPONSE,
            subject=f"Re: {original.subject}",
            payload=reply_payload,
            reply_to=original.id,
            references=[original.id, *original.references],
        )
        await self.send(reply_msg)
