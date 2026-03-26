"""Standardized bug reporting utility for QA agents.

Provides a consistent interface for creating bug reports and feature requests,
and formatting them for transmission over the message bus. This is a utility
class, not an agent -- it is used by QA agents to produce well-structured
reports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from agents.state import BugReport, BugSeverity, FeatureRequest, Priority

logger = structlog.get_logger()


class BugReporter:
    """Utility for creating standardized bug reports and feature requests.

    Encapsulates the conventions and validation logic for producing
    well-formed :class:`BugReport` and :class:`FeatureRequest` objects
    that can be persisted to project state and transmitted via the
    message bus.
    """

    @staticmethod
    def create_bug_report(
        title: str,
        description: str,
        severity: BugSeverity = BugSeverity.MAJOR,
        steps: list[str] | None = None,
        expected: str = "",
        actual: str = "",
        reporter: str = "",
        related_story: str | None = None,
        environment: str = "",
        logs: str = "",
    ) -> BugReport:
        """Create a validated :class:`BugReport` with sensible defaults.

        Args:
            title: Short, descriptive bug title.
            description: Detailed description of the defect.
            severity: How severe the bug is.
            steps: Ordered steps to reproduce the issue.
            expected: What *should* happen.
            actual: What *actually* happens.
            reporter: Agent ID of the reporter.
            related_story: Story ID this bug relates to, if any.
            environment: Runtime environment where the bug was observed.
            logs: Relevant log output or stack traces.

        Returns:
            A fully populated :class:`BugReport` instance.

        Raises:
            ValueError: If *title* or *description* is empty.
        """
        if not title or not title.strip():
            raise ValueError("Bug report title must not be empty")
        if not description or not description.strip():
            raise ValueError("Bug report description must not be empty")

        bug = BugReport(
            title=title.strip(),
            description=description.strip(),
            severity=severity,
            steps_to_reproduce=steps or [],
            expected_behavior=expected.strip() if expected else "",
            actual_behavior=actual.strip() if actual else "",
            reported_by=reporter,
            related_story=related_story,
            environment=environment.strip() if environment else "",
            logs=logs.strip() if logs else "",
        )

        logger.info(
            "bug_report_created",
            bug_id=bug.id,
            title=bug.title,
            severity=bug.severity.value,
            reporter=reporter,
        )

        return bug

    @staticmethod
    def create_feature_request(
        title: str,
        description: str,
        rationale: str = "",
        requested_by: str = "",
        priority: Priority = Priority.MEDIUM,
    ) -> FeatureRequest:
        """Create a validated :class:`FeatureRequest`.

        Args:
            title: Short, descriptive feature title.
            description: Detailed description of the desired behaviour.
            rationale: Business or UX justification for the request.
            requested_by: Agent ID of the requester.
            priority: Relative importance of the feature.

        Returns:
            A fully populated :class:`FeatureRequest` instance.

        Raises:
            ValueError: If *title* or *description* is empty.
        """
        if not title or not title.strip():
            raise ValueError("Feature request title must not be empty")
        if not description or not description.strip():
            raise ValueError("Feature request description must not be empty")

        fr = FeatureRequest(
            title=title.strip(),
            description=description.strip(),
            rationale=rationale.strip() if rationale else "",
            requested_by=requested_by,
            priority=priority,
        )

        logger.info(
            "feature_request_created",
            feature_id=fr.id,
            title=fr.title,
            requested_by=requested_by,
        )

        return fr

    @staticmethod
    def format_bug_for_message(bug: BugReport) -> dict[str, Any]:
        """Serialize a :class:`BugReport` into a dict suitable for message bus payloads.

        Args:
            bug: The bug report to serialize.

        Returns:
            A JSON-serializable dictionary representing the bug.
        """
        return {
            "bug_id": bug.id,
            "title": bug.title,
            "description": bug.description,
            "severity": bug.severity.value,
            "steps_to_reproduce": bug.steps_to_reproduce,
            "expected_behavior": bug.expected_behavior,
            "actual_behavior": bug.actual_behavior,
            "reported_by": bug.reported_by,
            "related_story": bug.related_story,
            "environment": bug.environment,
            "logs": bug.logs,
            "status": bug.status.value,
            "created_at": bug.created_at.isoformat(),
        }

    @staticmethod
    def format_feature_request_for_message(fr: FeatureRequest) -> dict[str, Any]:
        """Serialize a :class:`FeatureRequest` into a dict for message bus payloads.

        Args:
            fr: The feature request to serialize.

        Returns:
            A JSON-serializable dictionary representing the feature request.
        """
        return {
            "feature_id": fr.id,
            "title": fr.title,
            "description": fr.description,
            "rationale": fr.rationale,
            "requested_by": fr.requested_by,
            "priority": fr.priority.value,
            "created_at": fr.created_at.isoformat(),
            "converted_to_story": fr.converted_to_story,
        }
