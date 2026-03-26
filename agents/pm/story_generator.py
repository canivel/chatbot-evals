"""Story generation for the Product Manager agent.

Uses LLM calls to turn high-level requirements into detailed, well-structured
user stories with acceptance criteria, story points, and tags.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Coroutine

import structlog

from agents.state import AcceptanceCriteria, Priority, Story, TaskType

from .prompts import INITIAL_BACKLOG_PROMPT, STORY_GENERATION_PROMPT

logger = structlog.get_logger()

# Type alias for the LLM caller function that the agent provides.
LLMCaller = Callable[[list[dict[str, str]], bool], Coroutine[Any, Any, str]]

# Valid area tags for the chatbot eval platform.
VALID_AREAS = frozenset({"eval_engine", "connectors", "api", "frontend", "infra"})

# Mapping from area name to human-readable label used in prompts.
AREA_LABELS: dict[str, str] = {
    "eval_engine": "Evaluation Engine",
    "connectors": "LLM Provider Connectors",
    "api": "REST / WebSocket API",
    "frontend": "Dashboard Frontend",
    "infra": "Infrastructure & DevOps",
}

_PRIORITY_MAP: dict[str, Priority] = {
    "critical": Priority.CRITICAL,
    "high": Priority.HIGH,
    "medium": Priority.MEDIUM,
    "low": Priority.LOW,
}


class StoryGenerator:
    """Generates user stories from requirements via LLM.

    Parameters
    ----------
    llm_caller:
        An async function ``(messages, json_mode) -> str`` that calls the LLM.
        Typically bound to ``BaseAgent.call_llm`` with appropriate defaults.
    created_by:
        Agent identifier stamped on every generated story.
    """

    def __init__(self, llm_caller: LLMCaller, created_by: str = "pm") -> None:
        self._call_llm = llm_caller
        self._created_by = created_by

    # ------------------------------------------------------------------
    # Single-story generation
    # ------------------------------------------------------------------

    async def generate_story(
        self,
        requirement: str,
        area: str = "eval_engine",
    ) -> Story:
        """Generate a single detailed user story from a high-level requirement.

        Parameters
        ----------
        requirement:
            Free-text requirement description.
        area:
            Platform area (one of ``VALID_AREAS``).

        Returns
        -------
        Story
            A fully populated ``Story`` ready to be added to the backlog.

        Raises
        ------
        ValueError
            If *area* is not a recognised platform area.
        """
        if area not in VALID_AREAS:
            raise ValueError(
                f"Unknown area {area!r}. Must be one of {sorted(VALID_AREAS)}"
            )

        prompt = STORY_GENERATION_PROMPT.format(
            requirement=requirement,
            area=AREA_LABELS.get(area, area),
        )

        raw = await self._call_llm(
            [{"role": "user", "content": prompt}],
            True,
        )

        data = _parse_json(raw)
        return self._build_story(data, area)

    # ------------------------------------------------------------------
    # Initial backlog generation
    # ------------------------------------------------------------------

    async def generate_initial_backlog(
        self,
        story_count: int = 20,
    ) -> list[Story]:
        """Generate the initial product backlog for the chatbot eval platform.

        Uses the LLM to produce *story_count* stories spread across all five
        platform areas.  Dependency references (by title) are resolved into
        story IDs after generation.

        Returns
        -------
        list[Story]
            Ordered list of stories ready for the backlog.
        """
        prompt = INITIAL_BACKLOG_PROMPT.format(story_count=story_count)

        raw = await self._call_llm(
            [{"role": "user", "content": prompt}],
            True,
        )

        data = _parse_json(raw)
        raw_stories: list[dict[str, Any]] = data.get("stories", [])

        if not raw_stories:
            logger.warning("initial_backlog_empty_response")
            return []

        stories: list[Story] = []
        title_to_id: dict[str, str] = {}

        # First pass: create Story objects.
        for item in raw_stories:
            area = item.get("area", "eval_engine")
            if area not in VALID_AREAS:
                area = "eval_engine"
            story = self._build_story(item, area)
            stories.append(story)
            title_to_id[item.get("title", "")] = story.id

        # Second pass: resolve title-based dependencies to story IDs.
        for story, item in zip(stories, raw_stories):
            dep_titles: list[str] = item.get("depends_on_titles", [])
            for title in dep_titles:
                dep_id = title_to_id.get(title)
                if dep_id:
                    story.depends_on.append(dep_id)

        logger.info(
            "initial_backlog_generated",
            count=len(stories),
            areas={s.tags[0] if s.tags else "unknown" for s in stories},
        )
        return stories

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_story(self, data: dict[str, Any], area: str) -> Story:
        """Build a ``Story`` model from parsed LLM JSON output."""
        raw_priority = str(data.get("priority", "medium")).lower()
        priority = _PRIORITY_MAP.get(raw_priority, Priority.MEDIUM)

        raw_points = data.get("story_points", 3)
        story_points = _clamp_fibonacci(raw_points)

        raw_ac = data.get("acceptance_criteria", [])
        acceptance_criteria = [
            AcceptanceCriteria(description=str(ac)) for ac in raw_ac if ac
        ]

        tags = [str(t) for t in data.get("tags", [])]
        if area not in tags:
            tags.insert(0, area)

        return Story(
            title=str(data.get("title", "Untitled Story")),
            description=str(data.get("description", "")),
            task_type=TaskType.STORY,
            priority=priority,
            acceptance_criteria=acceptance_criteria,
            story_points=story_points,
            tags=tags,
            created_by=self._created_by,
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

_FIBONACCI = (1, 2, 3, 5, 8, 13)


def _clamp_fibonacci(value: Any) -> int:
    """Clamp *value* to the nearest fibonacci story-point value."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 3  # default to medium complexity
    # Find the closest fibonacci number.
    return min(_FIBONACCI, key=lambda f: abs(f - v))


def _parse_json(raw: str) -> dict[str, Any]:
    """Robustly parse JSON from an LLM response.

    Handles common issues like markdown code fences wrapping the JSON.
    """
    text = raw.strip()

    # Strip markdown code fences if present.
    if text.startswith("```"):
        # Remove opening fence (possibly ```json)
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("json_parse_failed", raw_length=len(raw), error=str(exc))
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object, got {type(result).__name__}")

    return result
