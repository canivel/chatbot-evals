"""Platform connectors for pulling conversation data from external chatbot platforms.

This package provides a :class:`BaseConnector` interface and concrete
implementations for various platforms and integration patterns:

- **MavenAGI** -- REST API connector for the MavenAGI platform.
- **Intercom** -- REST API v2 connector for Intercom conversations.
- **Zendesk** -- Chat / Messaging API connector for Zendesk.
- **Freshdesk** -- REST API v2 connector for Freshdesk ticket conversations.
- **Salesforce** -- REST API connector for Salesforce Service Cloud chat transcripts.
- **Drift** -- REST API connector for Drift conversations.
- **HubSpot** -- Conversations API v3 connector for HubSpot threads.
- **LiveChat** -- Agent Chat API v3.5 connector for LiveChat archives.
- **Crisp** -- REST API v1 connector for Crisp conversations.
- **Rasa** -- Tracker store connector for Rasa Open Source.
- **Botpress** -- Cloud API connector for Botpress conversations.
- **Amazon Connect** -- Transcript importer for Amazon Connect / Lex.
- **Gorgias** -- REST API connector for Gorgias support tickets.
- **Slack** -- Slack Bot connector for Slack-based chatbots.
- **Discord** -- Discord Bot connector for Discord-based chatbots.
- **Microsoft Teams** -- Teams Bot connector via Microsoft Graph API.
- **Dialogflow** -- Google Dialogflow CX/ES connector.
- **Ada** -- AI-first customer support platform connector.
- **Voiceflow** -- AI agent builder platform connector.
- **Cognigy** -- Enterprise conversational AI connector.
- **Yellow.ai** -- Enterprise AI chatbot connector.
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
from evalplatform.connectors.drift import DriftConfig, DriftConnector
from evalplatform.connectors.file_import import (
    FileImportConfig,
    FileImportConnector,
    FileFormat,
    ImportResult,
)
from evalplatform.connectors.freshdesk import FreshdeskConfig, FreshdeskConnector
from evalplatform.connectors.hubspot import HubSpotConfig, HubSpotConnector
from evalplatform.connectors.amazon_connect import AmazonConnectConfig, AmazonConnectConnector
from evalplatform.connectors.botpress import BotpressConfig, BotpressConnector
from evalplatform.connectors.crisp import CrispConfig, CrispConnector
from evalplatform.connectors.gorgias import GorgiasConfig, GorgiasConnector
from evalplatform.connectors.intercom import IntercomConfig, IntercomConnector
from evalplatform.connectors.livechat import LiveChatConfig, LiveChatConnector
from evalplatform.connectors.maven_agi import MavenAGIConfig, MavenAGIConnector
from evalplatform.connectors.rasa import RasaConfig, RasaConnector
from evalplatform.connectors.rest_api import (
    AuthType,
    PaginationType,
    RestAPIConfig,
    RestAPIConnector,
)
from evalplatform.connectors.dialogflow import DialogflowConfig, DialogflowConnector
from evalplatform.connectors.discord import DiscordConfig, DiscordConnector
from evalplatform.connectors.microsoft_teams import TeamsConfig, TeamsConnector
from evalplatform.connectors.salesforce import SalesforceConfig, SalesforceConnector
from evalplatform.connectors.slack import SlackConfig, SlackConnector
from evalplatform.connectors.webhook import WebhookConfig, WebhookConnector
from evalplatform.connectors.zendesk import ZendeskConfig, ZendeskConnector
from evalplatform.connectors.ada import AdaConfig, AdaConnector
from evalplatform.connectors.voiceflow import VoiceflowConfig, VoiceflowConnector
from evalplatform.connectors.cognigy import CognigyConfig, CognigyConnector
from evalplatform.connectors.yellow_ai import YellowAIConfig, YellowAIConnector

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
    # Crisp
    "CrispConfig",
    "CrispConnector",
    # Rasa
    "RasaConfig",
    "RasaConnector",
    # Botpress
    "BotpressConfig",
    "BotpressConnector",
    # Amazon Connect
    "AmazonConnectConfig",
    "AmazonConnectConnector",
    # Gorgias
    "GorgiasConfig",
    "GorgiasConnector",
    # Intercom
    "IntercomConfig",
    "IntercomConnector",
    # Zendesk
    "ZendeskConfig",
    "ZendeskConnector",
    # Freshdesk
    "FreshdeskConfig",
    "FreshdeskConnector",
    # Salesforce
    "SalesforceConfig",
    "SalesforceConnector",
    # Drift
    "DriftConfig",
    "DriftConnector",
    # HubSpot
    "HubSpotConfig",
    "HubSpotConnector",
    # LiveChat
    "LiveChatConfig",
    "LiveChatConnector",
    # Slack
    "SlackConfig",
    "SlackConnector",
    # Discord
    "DiscordConfig",
    "DiscordConnector",
    # Microsoft Teams
    "TeamsConfig",
    "TeamsConnector",
    # Dialogflow
    "DialogflowConfig",
    "DialogflowConnector",
    # Webhook
    "WebhookConfig",
    "WebhookConnector",
    # REST API
    "AuthType",
    "PaginationType",
    "RestAPIConfig",
    "RestAPIConnector",
    # Ada
    "AdaConfig",
    "AdaConnector",
    # Voiceflow
    "VoiceflowConfig",
    "VoiceflowConnector",
    # Cognigy
    "CognigyConfig",
    "CognigyConnector",
    # Yellow.ai
    "YellowAIConfig",
    "YellowAIConnector",
    # File Import
    "FileFormat",
    "FileImportConfig",
    "FileImportConnector",
    "ImportResult",
]
