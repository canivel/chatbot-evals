"""Tests for the inter-agent message bus."""

import asyncio
import pytest
from agents.message_bus import Message, MessageBus, MessageType


@pytest.fixture
def bus():
    return MessageBus()


def test_register_agent(bus):
    bus.register_agent("agent-1", team="engineering")
    assert "agent-1" in bus._queues
    assert "agent-1" in bus._team_members.get("engineering", set())


def test_register_agent_no_team(bus):
    bus.register_agent("agent-solo")
    assert "agent-solo" in bus._queues


def test_unregister_agent(bus):
    bus.register_agent("agent-1", team="qa")
    bus.unregister_agent("agent-1")
    assert "agent-1" not in bus._queues


@pytest.mark.asyncio
async def test_send_direct_message(bus):
    bus.register_agent("sender")
    bus.register_agent("receiver")

    msg = Message(
        from_agent="sender",
        to_agent="receiver",
        message_type=MessageType.TASK,
        subject="Test task",
        payload={"action": "build"},
    )
    await bus.send(msg)

    received = await bus.receive("receiver", timeout=1.0)
    assert received is not None
    assert received.subject == "Test task"
    assert received.from_agent == "sender"


@pytest.mark.asyncio
async def test_send_team_message(bus):
    bus.register_agent("sender")
    bus.register_agent("member-1", team="engineering")
    bus.register_agent("member-2", team="engineering")

    msg = Message(
        from_agent="sender",
        to_team="engineering",
        message_type=MessageType.STATUS_UPDATE,
        subject="Sprint started",
    )
    await bus.send(msg)

    r1 = await bus.receive("member-1", timeout=1.0)
    r2 = await bus.receive("member-2", timeout=1.0)
    assert r1 is not None
    assert r2 is not None


@pytest.mark.asyncio
async def test_broadcast(bus):
    bus.register_agent("sender")
    bus.register_agent("a1")
    bus.register_agent("a2")
    bus.register_agent("a3")

    msg = Message(
        from_agent="sender",
        message_type=MessageType.BROADCAST,
        subject="Announcement",
    )
    await bus.send(msg)

    # Sender should not receive own broadcast
    r_sender = await bus.receive("sender", timeout=0.5)
    assert r_sender is None

    r1 = await bus.receive("a1", timeout=1.0)
    assert r1 is not None


@pytest.mark.asyncio
async def test_receive_timeout(bus):
    bus.register_agent("lonely")
    result = await bus.receive("lonely", timeout=0.1)
    assert result is None


@pytest.mark.asyncio
async def test_receive_all(bus):
    bus.register_agent("sender")
    bus.register_agent("receiver")

    for i in range(3):
        await bus.send(Message(
            from_agent="sender",
            to_agent="receiver",
            message_type=MessageType.TASK,
            subject=f"Task {i}",
        ))

    messages = await bus.receive_all("receiver")
    assert len(messages) == 3


def test_get_history(bus):
    bus.register_agent("a1")
    bus.register_agent("a2")

    msg = Message(from_agent="a1", to_agent="a2", message_type=MessageType.TASK, subject="Test")
    asyncio.get_event_loop().run_until_complete(bus.send(msg))

    history = bus.get_history()
    assert len(history) == 1

    history_filtered = bus.get_history(agent_id="a1")
    assert len(history_filtered) == 1


def test_get_pending_count(bus):
    bus.register_agent("a1")
    assert bus.get_pending_count("a1") == 0
    assert bus.get_pending_count("nonexistent") == 0


def test_get_team_members(bus):
    bus.register_agent("m1", team="qa")
    bus.register_agent("m2", team="qa")
    bus.register_agent("m3", team="eng")

    qa_members = bus.get_team_members("qa")
    assert len(qa_members) == 2
    assert "m1" in qa_members


@pytest.mark.asyncio
async def test_reply(bus):
    bus.register_agent("requester")
    bus.register_agent("responder")

    original = Message(
        from_agent="requester",
        to_agent="responder",
        message_type=MessageType.QUERY,
        subject="Question",
    )
    await bus.send(original)

    received = await bus.receive("responder", timeout=1.0)
    await bus.reply(received, {"answer": "42"}, "responder")

    reply = await bus.receive("requester", timeout=1.0)
    assert reply is not None
    assert reply.reply_to == original.id
    assert reply.payload["answer"] == "42"
