"""Backlog management for the Product Manager agent.

Handles story prioritization, sprint capacity planning, velocity tracking,
and dynamic re-prioritization when bugs or urgent items arrive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from agents.state import (
    BugReport,
    Priority,
    SprintState,
    Story,
    StoryStatus,
    TaskType,
)

logger = structlog.get_logger()

# Default team capacity in story points per sprint.
DEFAULT_SPRINT_CAPACITY = 30

# Priority weight used for sorting; lower means higher urgency.
_PRIORITY_WEIGHTS: dict[Priority, int] = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
}

# Bug-fix stories receive a priority boost so they float to the top.
_BUG_FIX_BOOST = -1


@dataclass
class SprintPlan:
    """Result of sprint planning: selected stories, stretch goals, metadata."""

    sprint_number: int
    goal: str
    selected_stories: list[Story]
    stretch_stories: list[Story]
    total_points: int
    capacity: int
    risks: list[str] = field(default_factory=list)


class BacklogManager:
    """Prioritises stories and plans sprints.

    Responsibilities:
    - Sort and rank the backlog considering priority, dependencies, and type.
    - Group stories into sprint-sized batches.
    - Re-prioritise dynamically when bugs arrive.
    - Track historical velocity to inform capacity planning.
    """

    def __init__(self, capacity: int = DEFAULT_SPRINT_CAPACITY) -> None:
        self._capacity = capacity
        self._velocity_history: list[int] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def capacity(self) -> int:
        """Current sprint capacity in story points."""
        return self._capacity

    @capacity.setter
    def capacity(self, value: int) -> None:
        if value < 1:
            raise ValueError("Sprint capacity must be at least 1")
        self._capacity = value

    def get_average_velocity(self) -> float:
        """Return average velocity across tracked sprints, or 0 if none."""
        if not self._velocity_history:
            return 0.0
        return sum(self._velocity_history) / len(self._velocity_history)

    def record_velocity(self, sprint: SprintState) -> None:
        """Record the velocity from a completed sprint."""
        self._velocity_history.append(sprint.velocity)
        logger.info(
            "velocity_recorded",
            sprint=sprint.number,
            velocity=sprint.velocity,
            avg=self.get_average_velocity(),
        )

    def record_velocity_from_history(self, completed_sprints: list[SprintState]) -> None:
        """Bulk-import velocity from a list of completed sprints."""
        for sprint in completed_sprints:
            if sprint.velocity not in self._velocity_history:
                self._velocity_history.append(sprint.velocity)

    # ------------------------------------------------------------------
    # Prioritisation
    # ------------------------------------------------------------------

    def prioritize(self, stories: list[Story]) -> list[Story]:
        """Return *stories* sorted by effective priority.

        Ordering rules (applied in sequence):
        1. Bug-fix stories float above non-bug stories of the same priority.
        2. Higher priority (critical > high > medium > low).
        3. Stories with no unmet dependencies come before blocked ones.
        4. Smaller story-point estimates break ties (deliver value sooner).
        """
        return sorted(stories, key=lambda s: self._sort_key(s, stories))

    def reprioritize_for_bugs(
        self,
        stories: list[Story],
        bugs: list[BugReport],
    ) -> list[Story]:
        """Re-prioritise the backlog, boosting any story linked to an open bug.

        Bug-linked stories are promoted by one priority level (e.g. medium -> high).
        """
        open_bug_story_ids = {
            b.related_story for b in bugs if b.related_story and b.status != StoryStatus.DONE
        }

        adjusted: list[Story] = []
        for story in stories:
            if story.id in open_bug_story_ids or story.task_type == TaskType.BUG:
                promoted = self._promote_priority(story)
                adjusted.append(promoted)
            else:
                adjusted.append(story)

        return self.prioritize(adjusted)

    # ------------------------------------------------------------------
    # Sprint planning helpers
    # ------------------------------------------------------------------

    def suggest_sprint_scope(
        self,
        backlog: list[Story],
        capacity_override: int | None = None,
    ) -> SprintPlan:
        """Select stories for the next sprint based on capacity.

        Stories are taken in priority order until the capacity budget is
        exhausted.  Any remaining small stories (<=2 points) are added as
        stretch goals.
        """
        capacity = capacity_override or self._effective_capacity()
        prioritized = self.prioritize(backlog)

        selected: list[Story] = []
        stretch: list[Story] = []
        used_points = 0

        for story in prioritized:
            if used_points + story.story_points <= capacity:
                selected.append(story)
                used_points += story.story_points
            elif story.story_points <= 2:
                stretch.append(story)

        logger.info(
            "sprint_scope_suggested",
            selected=len(selected),
            stretch=len(stretch),
            total_points=used_points,
            capacity=capacity,
        )

        return SprintPlan(
            sprint_number=0,  # caller fills in actual number
            goal="",  # caller fills in from LLM
            selected_stories=selected,
            stretch_stories=stretch,
            total_points=used_points,
            capacity=capacity,
        )

    def group_by_sprint(
        self,
        stories: list[Story],
        capacity_override: int | None = None,
    ) -> list[list[Story]]:
        """Partition *stories* into sprint-sized groups.

        Useful for roadmap estimation.  Each group stays within the
        capacity budget.
        """
        capacity = capacity_override or self._effective_capacity()
        prioritized = self.prioritize(stories)

        sprints: list[list[Story]] = []
        current_sprint: list[Story] = []
        current_points = 0

        for story in prioritized:
            if current_points + story.story_points > capacity and current_sprint:
                sprints.append(current_sprint)
                current_sprint = []
                current_points = 0
            current_sprint.append(story)
            current_points += story.story_points

        if current_sprint:
            sprints.append(current_sprint)

        return sprints

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> dict[str, Any]:
        """Return backlog-management metrics."""
        avg = self.get_average_velocity()
        return {
            "capacity": self._capacity,
            "effective_capacity": self._effective_capacity(),
            "average_velocity": round(avg, 1),
            "sprints_tracked": len(self._velocity_history),
            "velocity_history": list(self._velocity_history),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _effective_capacity(self) -> int:
        """Use velocity-based capacity if we have history, else default."""
        avg = self.get_average_velocity()
        if avg > 0:
            # Use 90% of average velocity as a conservative target.
            return max(1, int(avg * 0.9))
        return self._capacity

    def _sort_key(self, story: Story, all_stories: list[Story]) -> tuple[int, int, int, int]:
        """Multi-factor sort key (lower = higher priority)."""
        priority_weight = _PRIORITY_WEIGHTS.get(story.priority, 2)

        # Bug-fix boost
        type_boost = _BUG_FIX_BOOST if story.task_type == TaskType.BUG else 0

        # Dependency penalty: stories whose dependencies are not DONE get pushed down.
        done_ids = {s.id for s in all_stories if s.status == StoryStatus.DONE}
        unmet = sum(1 for dep in story.depends_on if dep not in done_ids)
        dep_penalty = min(unmet, 3)  # cap to avoid extreme penalty

        return (
            priority_weight + type_boost,  # effective priority
            dep_penalty,                   # prefer unblocked stories
            story.story_points,            # prefer smaller stories (faster value)
            hash(story.id) & 0xFFFF,       # stable tiebreaker
        )

    @staticmethod
    def _promote_priority(story: Story) -> Story:
        """Return a copy of *story* with its priority promoted one level."""
        promotion_map: dict[Priority, Priority] = {
            Priority.LOW: Priority.MEDIUM,
            Priority.MEDIUM: Priority.HIGH,
            Priority.HIGH: Priority.CRITICAL,
            Priority.CRITICAL: Priority.CRITICAL,
        }
        new_priority = promotion_map[story.priority]
        if new_priority != story.priority:
            promoted = story.model_copy(update={"priority": new_priority})
            logger.debug(
                "story_priority_promoted",
                story_id=story.id,
                old=story.priority.value,
                new=new_priority.value,
            )
            return promoted
        return story
