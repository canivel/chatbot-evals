"""Shared project state for the multi-agent development team.

Central state store that all agents read from and write to.
Manages stories, tasks, bugs, sprint state, and project artifacts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StoryStatus(str, Enum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    IN_QA = "in_qa"
    DONE = "done"
    BLOCKED = "blocked"


class BugSeverity(str, Enum):
    BLOCKER = "blocker"
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    TRIVIAL = "trivial"


class TaskType(str, Enum):
    STORY = "story"
    BUG = "bug"
    FEATURE_REQUEST = "feature_request"
    RESEARCH = "research"
    SPIKE = "spike"


class AcceptanceCriteria(BaseModel):
    description: str
    met: bool = False


class Story(BaseModel):
    id: str = Field(default_factory=lambda: f"STORY-{uuid.uuid4().hex[:8].upper()}")
    title: str
    description: str
    task_type: TaskType = TaskType.STORY
    priority: Priority = Priority.MEDIUM
    status: StoryStatus = StoryStatus.BACKLOG
    acceptance_criteria: list[AcceptanceCriteria] = Field(default_factory=list)
    assigned_to: str | None = None
    assigned_team: str | None = None
    created_by: str = "pm"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sprint: int | None = None
    story_points: int = 1
    depends_on: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)


class BugReport(BaseModel):
    id: str = Field(default_factory=lambda: f"BUG-{uuid.uuid4().hex[:8].upper()}")
    title: str
    description: str
    severity: BugSeverity = BugSeverity.MAJOR
    steps_to_reproduce: list[str] = Field(default_factory=list)
    expected_behavior: str = ""
    actual_behavior: str = ""
    reported_by: str = ""
    assigned_to: str | None = None
    status: StoryStatus = StoryStatus.BACKLOG
    related_story: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    environment: str = ""
    logs: str = ""


class FeatureRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"FEAT-{uuid.uuid4().hex[:8].upper()}")
    title: str
    description: str
    rationale: str = ""
    requested_by: str = ""
    priority: Priority = Priority.MEDIUM
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    converted_to_story: str | None = None


class SprintState(BaseModel):
    number: int = 1
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stories: list[str] = Field(default_factory=list)
    completed_stories: list[str] = Field(default_factory=list)
    velocity: int = 0


class ProjectState(BaseModel):
    """Central state store for the entire multi-agent project."""

    project_name: str = "Chatbot Evals Platform"
    current_sprint: SprintState = Field(default_factory=SprintState)

    # Backlog and work items
    stories: dict[str, Story] = Field(default_factory=dict)
    bugs: dict[str, BugReport] = Field(default_factory=dict)
    feature_requests: dict[str, FeatureRequest] = Field(default_factory=dict)

    # Tracking
    completed_sprints: list[SprintState] = Field(default_factory=list)
    agent_activity_log: list[dict[str, Any]] = Field(default_factory=list)

    # Artifacts produced by agents
    artifacts: dict[str, str] = Field(default_factory=dict)

    def add_story(self, story: Story) -> str:
        self.stories[story.id] = story
        return story.id

    def add_bug(self, bug: BugReport) -> str:
        self.bugs[bug.id] = bug
        return bug.id

    def add_feature_request(self, fr: FeatureRequest) -> str:
        self.feature_requests[fr.id] = fr
        return fr.id

    def get_backlog(self, team: str | None = None) -> list[Story]:
        stories = [s for s in self.stories.values() if s.status == StoryStatus.BACKLOG]
        if team:
            stories = [s for s in stories if s.assigned_team == team]
        return sorted(stories, key=lambda s: list(Priority).index(s.priority))

    def get_sprint_stories(self) -> list[Story]:
        return [
            self.stories[sid]
            for sid in self.current_sprint.stories
            if sid in self.stories
        ]

    def move_story(self, story_id: str, new_status: StoryStatus) -> None:
        if story_id in self.stories:
            self.stories[story_id].status = new_status
            self.stories[story_id].updated_at = datetime.now(timezone.utc)
            if new_status == StoryStatus.DONE:
                self.current_sprint.completed_stories.append(story_id)

    def assign_story(self, story_id: str, agent_id: str, team: str) -> None:
        if story_id in self.stories:
            self.stories[story_id].assigned_to = agent_id
            self.stories[story_id].assigned_team = team

    def start_new_sprint(self) -> None:
        old_sprint = self.current_sprint.model_copy()
        old_sprint.velocity = len(old_sprint.completed_stories)
        self.completed_sprints.append(old_sprint)
        self.current_sprint = SprintState(number=old_sprint.number + 1)

    def log_activity(self, agent_id: str, action: str, details: dict[str, Any] | None = None) -> None:
        self.agent_activity_log.append({
            "agent_id": agent_id,
            "action": action,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_open_bugs(self) -> list[BugReport]:
        return [b for b in self.bugs.values() if b.status != StoryStatus.DONE]

    def get_metrics(self) -> dict[str, Any]:
        return {
            "total_stories": len(self.stories),
            "completed_stories": len([s for s in self.stories.values() if s.status == StoryStatus.DONE]),
            "open_bugs": len(self.get_open_bugs()),
            "current_sprint": self.current_sprint.number,
            "sprint_stories": len(self.current_sprint.stories),
            "sprint_completed": len(self.current_sprint.completed_stories),
            "total_sprints_completed": len(self.completed_sprints),
            "avg_velocity": (
                sum(s.velocity for s in self.completed_sprints) / len(self.completed_sprints)
                if self.completed_sprints
                else 0
            ),
        }
