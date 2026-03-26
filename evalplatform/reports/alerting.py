"""Alerting system for metric degradation and threshold violations."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertChannel(str, Enum):
    WEBHOOK = "webhook"
    EMAIL = "email"
    SLACK = "slack"
    LOG = "log"


class AlertRule(BaseModel):
    id: str
    name: str
    metric_name: str
    condition: str  # "below_threshold", "above_threshold", "degradation"
    threshold: float
    severity: AlertSeverity = AlertSeverity.WARNING
    channels: list[AlertChannel] = Field(default_factory=lambda: [AlertChannel.LOG])
    cooldown_minutes: int = 60
    is_active: bool = True


class Alert(BaseModel):
    id: str
    rule_id: str
    rule_name: str
    metric_name: str
    current_value: float
    threshold: float
    severity: AlertSeverity
    message: str
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None


class AlertEngine:
    """Evaluates alert rules against metric results and triggers alerts."""

    def __init__(self) -> None:
        self.rules: dict[str, AlertRule] = {}
        self.alerts: list[Alert] = []
        self._last_triggered: dict[str, datetime] = {}

    def add_rule(self, rule: AlertRule) -> None:
        self.rules[rule.id] = rule

    def remove_rule(self, rule_id: str) -> None:
        self.rules.pop(rule_id, None)

    def evaluate(self, metric_results: dict[str, float]) -> list[Alert]:
        """Evaluate all active rules against current metric results."""
        new_alerts = []
        now = datetime.now(timezone.utc)

        for rule in self.rules.values():
            if not rule.is_active:
                continue

            if rule.metric_name not in metric_results:
                continue

            # Check cooldown
            last = self._last_triggered.get(rule.id)
            if last:
                elapsed = (now - last).total_seconds() / 60
                if elapsed < rule.cooldown_minutes:
                    continue

            value = metric_results[rule.metric_name]
            triggered = False

            if rule.condition == "below_threshold" and value < rule.threshold:
                triggered = True
            elif rule.condition == "above_threshold" and value > rule.threshold:
                triggered = True

            if triggered:
                alert = Alert(
                    id=f"alert-{now.strftime('%Y%m%d%H%M%S')}-{rule.id}",
                    rule_id=rule.id,
                    rule_name=rule.name,
                    metric_name=rule.metric_name,
                    current_value=value,
                    threshold=rule.threshold,
                    severity=rule.severity,
                    message=self._format_alert_message(rule, value),
                )
                new_alerts.append(alert)
                self.alerts.append(alert)
                self._last_triggered[rule.id] = now
                logger.warning(
                    "alert_triggered",
                    rule=rule.name,
                    metric=rule.metric_name,
                    value=value,
                    threshold=rule.threshold,
                )

        return new_alerts

    def acknowledge_alert(self, alert_id: str, user: str) -> bool:
        for alert in self.alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                alert.acknowledged_at = datetime.now(timezone.utc)
                alert.acknowledged_by = user
                return True
        return False

    def get_active_alerts(self) -> list[Alert]:
        return [a for a in self.alerts if not a.acknowledged]

    def _format_alert_message(self, rule: AlertRule, value: float) -> str:
        direction = "below" if rule.condition == "below_threshold" else "above"
        return (
            f"[{rule.severity.value.upper()}] {rule.name}: "
            f"Metric '{rule.metric_name}' is {direction} threshold "
            f"(current: {value:.4f}, threshold: {rule.threshold:.4f})"
        )

    def get_default_rules(self) -> list[AlertRule]:
        """Return sensible default alert rules for chatbot eval."""
        return [
            AlertRule(
                id="hallucination-critical",
                name="High Hallucination Rate",
                metric_name="hallucination",
                condition="below_threshold",
                threshold=0.7,
                severity=AlertSeverity.CRITICAL,
            ),
            AlertRule(
                id="toxicity-critical",
                name="Toxicity Detected",
                metric_name="toxicity",
                condition="below_threshold",
                threshold=0.9,
                severity=AlertSeverity.CRITICAL,
            ),
            AlertRule(
                id="relevance-warning",
                name="Low Relevance",
                metric_name="relevance",
                condition="below_threshold",
                threshold=0.6,
                severity=AlertSeverity.WARNING,
            ),
            AlertRule(
                id="faithfulness-warning",
                name="Low Faithfulness",
                metric_name="faithfulness",
                condition="below_threshold",
                threshold=0.7,
                severity=AlertSeverity.WARNING,
            ),
            AlertRule(
                id="coherence-info",
                name="Low Coherence",
                metric_name="coherence",
                condition="below_threshold",
                threshold=0.6,
                severity=AlertSeverity.INFO,
            ),
        ]
