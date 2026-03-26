"""Worker for async connector sync operations."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


async def run_connector_sync(
    connector_id: str,
    connector_type: str,
    config: dict[str, Any],
    since: str | None = None,
) -> dict[str, Any]:
    """Sync conversations from a chatbot platform connector.

    Args:
        connector_id: Connector ID in the database.
        connector_type: Type of connector (maven_agi, intercom, etc.).
        config: Connector configuration (API keys, URLs, etc.).
        since: ISO timestamp to sync from (incremental sync).

    Returns:
        Dict with connector_id, status, conversations_synced, errors.
    """
    from evalplatform.connectors.base import ConnectorConfig

    logger.info(
        "connector_sync_started",
        connector_id=connector_id,
        connector_type=connector_type,
    )

    try:
        connector = _create_connector(connector_type, config)
        connected = await connector.connect()
        if not connected:
            return {
                "connector_id": connector_id,
                "status": "error",
                "conversations_synced": 0,
                "errors": ["Failed to connect"],
            }

        result = await connector.sync(since=since)
        await connector.disconnect()

        logger.info(
            "connector_sync_completed",
            connector_id=connector_id,
            synced=result.conversations_synced,
        )

        return {
            "connector_id": connector_id,
            "status": "completed",
            "conversations_synced": result.conversations_synced,
            "errors": result.errors,
            "duration_seconds": result.duration_seconds,
        }

    except Exception as e:
        logger.error("connector_sync_failed", connector_id=connector_id, error=str(e))
        return {
            "connector_id": connector_id,
            "status": "failed",
            "conversations_synced": 0,
            "errors": [str(e)],
        }


def _create_connector(connector_type: str, config: dict[str, Any]):
    """Factory to create connector instances for all 24 supported platforms."""
    from evalplatform.connectors.base import ConnectorConfig

    # Lazy imports to avoid loading all connectors at module level
    connector_map: dict[str, type] = {}

    def _load_map() -> dict[str, type]:
        if connector_map:
            return connector_map
        from evalplatform.connectors.maven_agi import MavenAGIConnector
        from evalplatform.connectors.intercom import IntercomConnector
        from evalplatform.connectors.zendesk import ZendeskConnector
        from evalplatform.connectors.webhook import WebhookConnector
        from evalplatform.connectors.rest_api import RestAPIConnector
        from evalplatform.connectors.file_import import FileImportConnector
        from evalplatform.connectors.ada import AdaConnector
        from evalplatform.connectors.salesforce import SalesforceConnector
        from evalplatform.connectors.dialogflow import DialogflowConnector
        from evalplatform.connectors.drift import DriftConnector
        from evalplatform.connectors.voiceflow import VoiceflowConnector
        from evalplatform.connectors.cognigy import CognigyConnector
        from evalplatform.connectors.yellow_ai import YellowAIConnector
        from evalplatform.connectors.rasa import RasaConnector
        from evalplatform.connectors.botpress import BotpressConnector
        from evalplatform.connectors.amazon_connect import AmazonConnectConnector
        from evalplatform.connectors.slack import SlackConnector
        from evalplatform.connectors.discord import DiscordConnector
        from evalplatform.connectors.microsoft_teams import TeamsConnector
        from evalplatform.connectors.freshdesk import FreshdeskConnector
        from evalplatform.connectors.hubspot import HubSpotConnector
        from evalplatform.connectors.livechat import LiveChatConnector
        from evalplatform.connectors.crisp import CrispConnector
        from evalplatform.connectors.gorgias import GorgiasConnector

        connector_map.update({
            # AI Chatbot Platforms
            "maven_agi": MavenAGIConnector,
            "intercom": IntercomConnector,
            "zendesk": ZendeskConnector,
            "ada": AdaConnector,
            "salesforce": SalesforceConnector,
            "dialogflow": DialogflowConnector,
            "drift": DriftConnector,
            "voiceflow": VoiceflowConnector,
            "cognigy": CognigyConnector,
            "yellow_ai": YellowAIConnector,
            "rasa": RasaConnector,
            "botpress": BotpressConnector,
            "amazon_connect": AmazonConnectConnector,
            # Messaging & Support
            "slack": SlackConnector,
            "discord": DiscordConnector,
            "microsoft_teams": TeamsConnector,
            "freshdesk": FreshdeskConnector,
            "hubspot": HubSpotConnector,
            "livechat": LiveChatConnector,
            "crisp": CrispConnector,
            "gorgias": GorgiasConnector,
            # Generic
            "webhook": WebhookConnector,
            "rest_api": RestAPIConnector,
            "file_import": FileImportConnector,
        })
        return connector_map

    mapping = _load_map()
    connector_class = mapping.get(connector_type)
    if not connector_class:
        raise ValueError(f"Unknown connector type: {connector_type}. Available: {sorted(mapping.keys())}")

    connector_config = ConnectorConfig(
        name=config.get("name", connector_type),
        connector_type=connector_type,
        credentials=config.get("credentials", {}),
        settings=config.get("settings", {}),
    )

    return connector_class(connector_config)
