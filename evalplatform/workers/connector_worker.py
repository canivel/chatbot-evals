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
    """Factory to create connector instances."""
    from evalplatform.connectors.maven_agi import MavenAGIConnector
    from evalplatform.connectors.intercom import IntercomConnector
    from evalplatform.connectors.zendesk import ZendeskConnector
    from evalplatform.connectors.webhook import WebhookConnector
    from evalplatform.connectors.rest_api import RestAPIConnector
    from evalplatform.connectors.file_import import FileImportConnector
    from evalplatform.connectors.base import ConnectorConfig

    connector_map = {
        "maven_agi": MavenAGIConnector,
        "intercom": IntercomConnector,
        "zendesk": ZendeskConnector,
        "webhook": WebhookConnector,
        "rest_api": RestAPIConnector,
        "file_import": FileImportConnector,
    }

    connector_class = connector_map.get(connector_type)
    if not connector_class:
        raise ValueError(f"Unknown connector type: {connector_type}")

    connector_config = ConnectorConfig(
        name=config.get("name", connector_type),
        connector_type=connector_type,
        credentials=config.get("credentials", {}),
        settings=config.get("settings", {}),
    )

    return connector_class(connector_config)
