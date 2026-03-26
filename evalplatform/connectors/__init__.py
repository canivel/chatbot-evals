"""Platform connectors for pulling conversation data from external chatbot platforms.

This package provides a :class:`BaseConnector` interface and concrete
implementations for various platforms and integration patterns:

- **MavenAGI** -- REST API connector for the MavenAGI platform.
- **Intercom** -- REST API v2 connector for Intercom conversations.
- **Zendesk** -- Chat / Messaging API connector for Zendesk.
- **Webhook** -- Generic inbound webhook receiver.
- **REST API** -- Generic configurable REST endpoint poller.
- **File Import** -- CSV / JSON / JSONL file importer.
"""

from evalplatform.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorStatus,
    ConversationData,
    MessageData,
    SyncResult,
)
from evalplatform.connectors.file_import import (
    FileImportConfig,
    FileImportConnector,
    FileFormat,
    ImportResult,
)
from evalplatform.connectors.intercom import IntercomConfig, IntercomConnector
from evalplatform.connectors.maven_agi import MavenAGIConfig, MavenAGIConnector
from evalplatform.connectors.rest_api import (
    AuthType,
    PaginationType,
    RestAPIConfig,
    RestAPIConnector,
)
from evalplatform.connectors.webhook import WebhookConfig, WebhookConnector
from evalplatform.connectors.zendesk import ZendeskConfig, ZendeskConnector

__all__ = [
    # Base
    "BaseConnector",
    "ConnectorConfig",
    "ConnectorStatus",
    "ConversationData",
    "MessageData",
    "SyncResult",
    # MavenAGI
    "MavenAGIConfig",
    "MavenAGIConnector",
    # Intercom
    "IntercomConfig",
    "IntercomConnector",
    # Zendesk
    "ZendeskConfig",
    "ZendeskConnector",
    # Webhook
    "WebhookConfig",
    "WebhookConnector",
    # REST API
    "AuthType",
    "PaginationType",
    "RestAPIConfig",
    "RestAPIConnector",
    # File Import
    "FileFormat",
    "FileImportConfig",
    "FileImportConnector",
    "ImportResult",
]
