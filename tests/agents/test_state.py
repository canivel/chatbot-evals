"""Tests for the shared project state."""

import pytest
from agents.state import (
    AcceptanceCriteria,
    BugReport,
    BugSeverity,
    FeatureRequest,
    Priority,
    ProjectState,
    Story,
    StoryStatus,
    TaskType,
)


def test_create_story():
    story = Story(
        title="Implement faithfulness metric",
        description="Create the faithfulness eval metric",
        priority=Priority.HIGH,
        tags=["eval", "metrics"],
    )
    assert story.id.startswith("STORY-")
    assert story.status == StoryStatus.BACKLOG
    assert story.priority == Priority.HIGH


def test_add_story_to_state():
    state = ProjectState()
    story = Story(title="Test story", description="A test")
    story_id = state.add_story(story)
    assert story_id in state.stories
    assert state.stories[story_id].title == "Test story"


def test_add_bug_to_state():
    state = ProjectState()
    bug = BugReport(
        title="API returns 500",
        description="The /evals endpoint crashes",
        severity=BugSeverity.CRITICAL,
        steps_to_reproduce=["POST /evals with empty body"],
        reported_by="qa-functional",
    )
    bug_id = state.add_bug(bug)
    assert bug_id in state.bugs
    assert state.bugs[bug_id].severity == BugSeverity.CRITICAL


def test_get_backlog():
    state = ProjectState()
    state.add_story(Story(title="High priority", description="", priority=Priority.HIGH))
    state.add_story(Story(title="Low priority", description="", priority=Priority.LOW))
    state.add_story(Story(title="Critical", description="", priority=Priority.CRITICAL))

    backlog = state.get_backlog()
    assert len(backlog) == 3
    # Should be sorted by priority
    assert backlog[0].priority == Priority.CRITICAL
    assert backlog[1].priority == Priority.HIGH


def test_move_story():
    state = ProjectState()
    story = Story(title="Test", description="")
    sid = state.add_story(story)
    state.current_sprint.stories.append(sid)

    state.move_story(sid, StoryStatus.IN_PROGRESS)
    assert state.stories[sid].status == StoryStatus.IN_PROGRESS

    state.move_story(sid, StoryStatus.DONE)
    assert state.stories[sid].status == StoryStatus.DONE
    assert sid in state.current_sprint.completed_stories


def test_assign_story():
    state = ProjectState()
    story = Story(title="Test", description="")
    sid = state.add_story(story)

    state.assign_story(sid, "eng-backend", "engineering")
    assert state.stories[sid].assigned_to == "eng-backend"
    assert state.stories[sid].assigned_team == "engineering"


def test_start_new_sprint():
    state = ProjectState()
    assert state.current_sprint.number == 1

    state.start_new_sprint()
    assert state.current_sprint.number == 2
    assert len(state.completed_sprints) == 1


def test_get_metrics():
    state = ProjectState()
    state.add_story(Story(title="S1", description="", status=StoryStatus.DONE))
    state.add_story(Story(title="S2", description="", status=StoryStatus.IN_PROGRESS))
    state.add_bug(BugReport(title="B1", description=""))

    metrics = state.get_metrics()
    assert metrics["total_stories"] == 2
    assert metrics["completed_stories"] == 1
    assert metrics["open_bugs"] == 1


def test_get_open_bugs():
    state = ProjectState()
    state.add_bug(BugReport(title="Open bug", description=""))
    done_bug = BugReport(title="Fixed bug", description="", status=StoryStatus.DONE)
    state.add_bug(done_bug)

    open_bugs = state.get_open_bugs()
    assert len(open_bugs) == 1
    assert open_bugs[0].title == "Open bug"


def test_feature_request():
    state = ProjectState()
    fr = FeatureRequest(
        title="Add Slack connector",
        description="Connect to Slack for chatbot eval",
        rationale="Many companies use Slack bots",
        requested_by="qa-functional",
    )
    fr_id = state.add_feature_request(fr)
    assert fr_id in state.feature_requests


def test_log_activity():
    state = ProjectState()
    state.log_activity("pm-lead", "created_story", {"story_id": "STORY-001"})
    assert len(state.agent_activity_log) == 1
    assert state.agent_activity_log[0]["agent_id"] == "pm-lead"
