# Integrations Guide

The Chatbot Evals Platform ingests conversation data from external chatbot platforms through **connectors**. Each connector implements a common interface (`BaseConnector`) that handles connection lifecycle, data fetching, and synchronisation.

This document covers setup, configuration, and data mapping for every supported connector type.

---

## Table of Contents

- [Common Concepts](#common-concepts)
- [MavenAGI](#mavenagi)
- [Intercom](#intercom)
- [Zendesk](#zendesk)
- [Generic Webhook](#generic-webhook)
- [Generic REST API](#generic-rest-api)
- [File Import](#file-import)

---

## Common Concepts

### Connector Lifecycle

Every connector follows the same lifecycle:

1. **Create** -- register the connector via `POST /api/v1/connectors` with a `connector_type` and a `config` object.
2. **Connect** -- the platform establishes a connection (HTTP client, webhook listener, etc.) and validates credentials.
3. **Sync** -- `POST /api/v1/connectors/{id}/sync` triggers a data pull. Conversations are fetched, mapped to the canonical `ConversationData` model, and stored.
4. **Disconnect** -- resources are released when the connector is deactivated or deleted.

### Canonical Data Model

All connectors normalise external data into these shared models:

```
ConversationData
  external_id   -- unique ID on the source platform
  messages[]    -- ordered list of MessageData
  metadata      -- platform-specific key/value pairs
  started_at    -- conversation start timestamp (UTC)
  ended_at      -- conversation end timestamp (UTC)

MessageData
  role          -- "user", "assistant", or "system"
  content       -- text content of the message
  timestamp     -- when the message was sent (UTC)
  metadata      -- additional per-message metadata
```

### Connector Types (enum)

| Value          | Description                                |
|----------------|--------------------------------------------|
| `maven_agi`   | MavenAGI conversational AI platform        |
| `intercom`    | Intercom REST API v2                       |
| `zendesk`     | Zendesk Chat / Messaging API               |
| `webhook`     | Generic inbound webhook receiver           |
| `rest_api`    | Generic configurable REST endpoint poller  |
| `file_import` | CSV / JSON / JSONL file importer           |

---

## MavenAGI

### Overview

The MavenAGI connector fetches conversation data from the MavenAGI conversational AI platform via its REST API. Endpoint paths are configurable to accommodate different deployment environments.

### Required Credentials

| Field              | Type   | Description                                        |
|--------------------|--------|----------------------------------------------------|
| `api_key`          | string | MavenAGI API key (sent as `Bearer` token)          |
| `base_url`         | string | API base URL (default: `https://api.mavenagi.com/v1`) |
| `organization_id`  | string | MavenAGI organization identifier                   |

### Creating the Connector

```bash
curl -X POST http://localhost:8000/api/v1/connectors \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "MavenAGI Production",
    "connector_type": "maven_agi",
    "config": {
      "api_key": "maven-api-key-here",
      "base_url": "https://api.mavenagi.com/v1",
      "organization_id": "org-123456",
      "timeout_seconds": 30
    }
  }'
```

### How Conversations Are Fetched

1. The connector calls `GET /conversations` with `organization_id`, `limit`, and optional `updated_after` parameters.
2. Results are paginated using **cursor-based pagination** -- the response includes a `next_cursor` field that is passed as a `cursor` query parameter on subsequent requests.
3. Fetching continues until the requested limit is reached or no more pages are available.
4. Individual conversations can be fetched via `GET /conversations/{conversation_id}`.

### Connection Test

The connector validates credentials by calling `GET /health` on the MavenAGI API.

### Data Mapping

| MavenAGI Field                  | Mapped To                         |
|---------------------------------|-----------------------------------|
| `id`                            | `ConversationData.external_id`    |
| `messages[].text`               | `MessageData.content`             |
| `messages[].author.type`        | `MessageData.role` (normalised)   |
| `messages[].created_at`         | `MessageData.timestamp`           |
| `created_at`                    | `ConversationData.started_at`     |
| `ended_at`                      | `ConversationData.ended_at`       |
| All other top-level fields      | `ConversationData.metadata`       |

**Role normalisation:**

| MavenAGI Author Type              | Normalised Role |
|------------------------------------|-----------------|
| `user`, `human`, `end_user`       | `user`          |
| `bot`, `agent`, `assistant`       | `assistant`     |
| `system`                          | `system`        |

### HTTP Headers Sent

```
Authorization: Bearer <api_key>
Accept: application/json
X-Organization-Id: <organization_id>
```

---

## Intercom

### Overview

The Intercom connector fetches conversations from the Intercom REST API v2. It retrieves conversation lists and then fetches full conversation details (including conversation parts) for each one.

**API Reference:** https://developers.intercom.com/docs/references/rest-api/api.intercom.io/conversations/

### Required Credentials

| Field           | Type   | Description                                         |
|-----------------|--------|-----------------------------------------------------|
| `access_token`  | string | Intercom access token (OAuth or personal)           |
| `workspace_id`  | string | Intercom workspace ID (used for logging/filtering)  |

### Optional Settings

| Field              | Type   | Default | Description                             |
|--------------------|--------|---------|-----------------------------------------|
| `timeout_seconds`  | float  | 30.0    | HTTP request timeout in seconds         |
| `page_size`        | int    | 50      | Conversations per page (1-150)          |

### Creating the Connector

```bash
curl -X POST http://localhost:8000/api/v1/connectors \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Intercom Support",
    "connector_type": "intercom",
    "config": {
      "access_token": "your-intercom-access-token",
      "workspace_id": "abc12345",
      "page_size": 50
    }
  }'
```

### Connection Test

The connector validates the access token by calling `GET /me` on the Intercom API.

### How Conversations Are Fetched

1. The connector calls `GET /conversations` with `per_page` and optional `updated_after` (epoch seconds) parameters.
2. For each conversation in the list response, a detail request is made to `GET /conversations/{id}` to retrieve full conversation parts (the list endpoint often lacks full message content).
3. If the detail request fails, the connector falls back to the summary representation from the list response.
4. **Pagination** is handled using Intercom's `pages.next` object, which may contain a `starting_after` cursor or a full URL.

### Conversation Parts Mapping

Intercom conversations have two types of content:

1. **Source** -- the initial message (typically from the user), found in the `source` field.
2. **Conversation Parts** -- subsequent messages found in `conversation_parts.conversation_parts[]`. Only parts with a non-empty body are included.

| Intercom Field                          | Mapped To                         |
|-----------------------------------------|-----------------------------------|
| `id`                                    | `ConversationData.external_id`    |
| `source.body`                           | First `MessageData.content`       |
| `source.author.type`                    | First `MessageData.role`          |
| `conversation_parts[].body`             | `MessageData.content`             |
| `conversation_parts[].author.type`      | `MessageData.role` (normalised)   |
| `conversation_parts[].created_at`       | `MessageData.timestamp`           |
| `created_at`                            | `ConversationData.started_at`     |
| `updated_at`                            | `ConversationData.ended_at`       |
| `state`, `tags`, `assignee`, `statistics` | `ConversationData.metadata`     |

**Role normalisation:**

| Intercom Author Type              | Normalised Role |
|------------------------------------|-----------------|
| `user`, `lead`, `contact`         | `user`          |
| `admin`, `bot`, `team`            | `assistant`     |

### HTTP Headers Sent

```
Authorization: Bearer <access_token>
Accept: application/json
Intercom-Version: 2.10
```

---

## Zendesk

### Overview

The Zendesk connector fetches chat transcripts from the Zendesk Chat API and maps them to the canonical conversation model. It supports both the legacy Chat API history format and the newer messages format.

**API References:**
- Chat API: https://developer.zendesk.com/api-reference/live-chat/chat-api/chats/
- Sunshine Conversations: https://developer.zendesk.com/api-reference/agent-workspace/

### Required Credentials

| Field        | Type   | Description                                          |
|--------------|--------|------------------------------------------------------|
| `subdomain`  | string | Zendesk subdomain (e.g. `acme` for `acme.zendesk.com`) |
| `api_token`  | string | Zendesk API token                                    |
| `email`      | string | Email address associated with the API token          |

### Optional Settings

| Field              | Type   | Default | Description                            |
|--------------------|--------|---------|----------------------------------------|
| `timeout_seconds`  | float  | 30.0    | HTTP request timeout in seconds        |
| `page_size`        | int    | 100     | Chats per page (1-200)                 |

### Creating the Connector

```bash
curl -X POST http://localhost:8000/api/v1/connectors \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Zendesk Chat",
    "connector_type": "zendesk",
    "config": {
      "subdomain": "acme",
      "api_token": "zendesk-api-token-here",
      "email": "admin@acme.com",
      "page_size": 100
    }
  }'
```

### Connection Test

The connector validates credentials by calling `GET /api/v2/account`.

### How Conversations Are Fetched

1. The connector calls `GET /api/v2/chats` with `limit` and optional `start_time` (epoch seconds) parameters.
2. Responses are paginated using `next_page` or `next_url` fields returned in the response body.
3. Individual chats can be fetched via `GET /api/v2/chats/{chat_id}`.

### Chat Transcript Mapping

Zendesk chats store messages in a `history` array of events. Only message-type events (`chat.msg`, `chat.message`, `msg`) are extracted; join, leave, and system events are skipped.

If the `history` field is empty, the connector falls back to a top-level `messages` array.

| Zendesk Field                    | Mapped To                         |
|----------------------------------|-----------------------------------|
| `id`                             | `ConversationData.external_id`    |
| `history[].msg` / `.message`     | `MessageData.content`             |
| `history[].sender_type`          | `MessageData.role` (normalised)   |
| `history[].timestamp`            | `MessageData.timestamp`           |
| `started_at` / `start_timestamp` | `ConversationData.started_at`     |
| `ended_at` / `end_timestamp`     | `ConversationData.ended_at`       |
| `department_name`, `tags`, `rating`, `visitor`, `agent_names` | `ConversationData.metadata` |

**Role normalisation:**

| Zendesk Sender Type                | Normalised Role |
|-------------------------------------|-----------------|
| `visitor`, `customer`, `end_user`, `user` | `user`    |
| `agent`, `admin`                   | `assistant`     |
| `trigger`, `system`               | `system`        |

### Authentication

Zendesk uses **HTTP Basic authentication** with the format `{email}/token:{api_token}`, Base64-encoded.

---

## Generic Webhook

### Overview

The webhook connector receives conversation data via inbound HTTP POST requests. It validates optional HMAC signatures and stores incoming conversations in memory for retrieval by the eval engine.

This connector is ideal for platforms that support outbound webhooks (e.g. on conversation close) but do not have a pull-based API.

### Creating the Connector

```bash
curl -X POST http://localhost:8000/api/v1/connectors \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Custom Webhook",
    "connector_type": "webhook",
    "config": {
      "webhook_secret": "your-shared-secret",
      "signature_header": "X-Signature-256",
      "signature_algorithm": "sha256",
      "max_stored_conversations": 10000,
      "field_mapping": {
        "conversation_id": "data.conversation.id",
        "messages": "data.conversation.messages",
        "message_role": "sender_type",
        "message_content": "text",
        "message_timestamp": "sent_at",
        "started_at": "data.conversation.created_at",
        "ended_at": "data.conversation.closed_at"
      }
    }
  }'
```

### Webhook Signature Validation (HMAC)

If a `webhook_secret` is configured, every inbound POST must include a valid HMAC signature.

**How it works:**

1. The payload JSON is serialised with compact separators and sorted keys: `json.dumps(payload, separators=(",", ":"), sort_keys=True)`.
2. An HMAC digest is computed using the configured algorithm (default: `sha256`) and the shared secret.
3. The signature is read from the HTTP header specified by `signature_header` (default: `X-Signature-256`).
4. Both `sha256=<hex>` prefix format and raw hex are accepted.
5. Comparison uses constant-time `hmac.compare_digest` to prevent timing attacks.

If the signature is missing or invalid, the request is rejected with a `403 Forbidden` error.

### Configuration Fields

| Field                      | Type   | Default           | Description                                      |
|----------------------------|--------|-------------------|--------------------------------------------------|
| `webhook_secret`           | string | `""`              | Shared secret for HMAC validation (empty = no validation) |
| `signature_header`         | string | `X-Signature-256` | HTTP header carrying the HMAC signature          |
| `signature_algorithm`      | string | `sha256`          | Hash algorithm (`sha256`, `sha1`)                |
| `max_stored_conversations` | int    | 10000             | Maximum conversations to keep in memory          |

### Payload Field Mapping

The `field_mapping` object uses dot-separated paths to extract values from arbitrarily structured JSON payloads.

| Mapping Field        | Default          | Description                                       |
|----------------------|------------------|---------------------------------------------------|
| `conversation_id`    | `id`             | Path to the conversation external ID              |
| `messages`           | `messages`       | Path to the messages array                        |
| `message_role`       | `role`           | Path (relative to each message) to the role       |
| `message_content`    | `content`        | Path (relative to each message) to text content   |
| `message_timestamp`  | `timestamp`      | Path (relative to each message) to timestamp      |
| `started_at`         | `started_at`     | Path to conversation start timestamp              |
| `ended_at`           | `ended_at`       | Path to conversation end timestamp                |

### Example Payloads

**Simple (default mapping):**

```json
{
  "id": "conv-001",
  "started_at": "2025-01-15T10:00:00Z",
  "ended_at": "2025-01-15T10:05:00Z",
  "messages": [
    {
      "role": "user",
      "content": "How do I reset my password?",
      "timestamp": "2025-01-15T10:00:00Z"
    },
    {
      "role": "assistant",
      "content": "Go to Settings > Security > Reset Password.",
      "timestamp": "2025-01-15T10:00:15Z"
    }
  ]
}
```

**Nested (custom mapping):**

With `field_mapping`:
```json
{
  "conversation_id": "data.chat.id",
  "messages": "data.chat.transcript",
  "message_role": "sender",
  "message_content": "body",
  "message_timestamp": "ts"
}
```

Payload:
```json
{
  "event": "conversation.closed",
  "data": {
    "chat": {
      "id": "chat-abc-123",
      "transcript": [
        {"sender": "user", "body": "Hello!", "ts": 1705312800},
        {"sender": "assistant", "body": "Hi, how can I help?", "ts": 1705312810}
      ]
    }
  }
}
```

---

## Generic REST API

### Overview

The REST API connector polls a configurable REST endpoint on demand (or on a schedule) and maps the JSON response to conversation data. It supports multiple authentication methods and pagination patterns.

### Required Configuration

| Field     | Type   | Description                                |
|-----------|--------|--------------------------------------------|
| `url`     | string | Base URL of the conversations endpoint     |

### Authentication Types

The `auth_type` field controls how requests are authenticated.

| `auth_type` | Required Fields                         | Header Sent                                         |
|-------------|-----------------------------------------|-----------------------------------------------------|
| `bearer`    | `auth_token`                            | `Authorization: Bearer <auth_token>`                |
| `basic`     | `auth_username`, `auth_password`        | `Authorization: Basic <base64(user:pass)>`          |
| `api_key`   | `auth_token`, `api_key_header`          | `<api_key_header>: <auth_token>` (default: `X-API-Key`) |
| `none`      | none                                    | No auth header                                      |

### Creating the Connector

```bash
curl -X POST http://localhost:8000/api/v1/connectors \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Custom API",
    "connector_type": "rest_api",
    "config": {
      "url": "https://api.example.com/v1/conversations",
      "auth_type": "bearer",
      "auth_token": "your-api-token",
      "polling_interval_seconds": 300,
      "timeout_seconds": 30,
      "headers": {
        "X-Custom-Header": "value"
      },
      "pagination": {
        "type": "cursor",
        "page_size": 100,
        "cursor_param": "cursor",
        "cursor_response_path": "meta.next_cursor"
      },
      "response_mapping": {
        "conversations_path": "data.conversations",
        "conversation_id": "id",
        "messages_path": "messages",
        "message_role": "role",
        "message_content": "text",
        "message_timestamp": "created_at",
        "started_at": "started_at",
        "ended_at": "ended_at"
      }
    }
  }'
```

### Pagination Types

| `type`     | Description                                       | Key Config Fields                                              |
|------------|---------------------------------------------------|----------------------------------------------------------------|
| `offset`   | Traditional offset/limit pagination               | `offset_param`, `limit_param`, `total_path`                    |
| `cursor`   | Cursor-based pagination                           | `cursor_param`, `cursor_response_path`                         |
| `next_url` | Server returns a full URL for the next page       | `next_url_response_path`                                       |
| `none`     | No pagination (single request)                    | n/a                                                            |

**Full pagination config:**

| Field                   | Default        | Description                                          |
|-------------------------|----------------|------------------------------------------------------|
| `type`                  | `none`         | Pagination strategy                                  |
| `page_size`             | 100            | Items per page (1-1000)                              |
| `offset_param`          | `offset`       | Query param for offset pagination                    |
| `limit_param`           | `limit`        | Query param for page size                            |
| `cursor_param`          | `cursor`       | Query param for cursor value                         |
| `cursor_response_path`  | `next_cursor`  | Dot-path to cursor in response JSON                  |
| `next_url_response_path`| `next`         | Dot-path to next-page URL in response JSON           |
| `total_path`            | `total`        | Dot-path to total count (for offset pagination)      |
| `max_pages`             | 100            | Safety limit on number of pages to fetch             |

### Response Mapping

The `response_mapping` object uses dot-separated paths to locate data in the API response.

| Mapping Field        | Default        | Description                                          |
|----------------------|----------------|------------------------------------------------------|
| `conversations_path` | `data`         | Path to the conversations array in the response      |
| `conversation_id`    | `id`           | Path (relative to conversation) to its external ID   |
| `messages_path`      | `messages`     | Path (relative to conversation) to the messages array|
| `message_role`       | `role`         | Path (relative to message) to the role               |
| `message_content`    | `content`      | Path (relative to message) to text content           |
| `message_timestamp`  | `timestamp`    | Path (relative to message) to the timestamp          |
| `started_at`         | `started_at`   | Path (relative to conversation) to start timestamp   |
| `ended_at`           | `ended_at`     | Path (relative to conversation) to end timestamp     |

### Connection Test

The connector makes a lightweight `GET` request to the configured URL with `?limit=1` to verify connectivity.

---

## File Import

### Overview

The file import connector loads conversation data from local files or uploaded content in CSV, JSON, or JSONL format. Column/field mapping is configurable so that arbitrary file schemas can be normalised.

### Supported Formats

| Format | Extension | Description                                          |
|--------|-----------|------------------------------------------------------|
| `csv`  | `.csv`    | One row per message, grouped by conversation ID      |
| `json` | `.json`   | Array of conversation objects (or object with array key) |
| `jsonl`| `.jsonl`  | One JSON conversation object per line                |

### Creating the Connector

```bash
curl -X POST http://localhost:8000/api/v1/connectors \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "CSV Import",
    "connector_type": "file_import",
    "config": {
      "file_format": "csv",
      "encoding": "utf-8",
      "csv_delimiter": ",",
      "batch_size": 500,
      "column_mapping": {
        "conversation_id": "conversation_id",
        "message_role": "role",
        "message_content": "content",
        "message_timestamp": "timestamp",
        "started_at": "started_at",
        "ended_at": "ended_at",
        "messages_path": "messages"
      }
    }
  }'
```

### Column / Field Mapping

| Mapping Field        | Default            | Description                                             |
|----------------------|--------------------|---------------------------------------------------------|
| `conversation_id`    | `conversation_id`  | CSV column or JSON path for the conversation external ID|
| `message_role`       | `role`             | Column/path for the message role                        |
| `message_content`    | `content`          | Column/path for the message text                        |
| `message_timestamp`  | `timestamp`        | Column/path for the message timestamp                   |
| `started_at`         | `started_at`       | Column/path for conversation start time                 |
| `ended_at`           | `ended_at`         | Column/path for conversation end time                   |
| `messages_path`      | `messages`         | Dot-path to messages array (JSON/JSONL only)            |

### CSV Format

CSV files must have **one row per message**. Rows are grouped by the `conversation_id` column to form conversations. Three columns are required: the conversation ID, the message role, and the message content.

**Example CSV:**

```csv
conversation_id,role,content,timestamp,started_at,ended_at
conv-001,user,"How do I reset my password?",2025-01-15T10:00:00Z,2025-01-15T10:00:00Z,2025-01-15T10:05:00Z
conv-001,assistant,"Go to Settings > Security > Reset Password.",2025-01-15T10:00:15Z,,
conv-002,user,"What are your hours?",2025-01-15T11:00:00Z,2025-01-15T11:00:00Z,2025-01-15T11:02:00Z
conv-002,assistant,"We are open 9 AM to 5 PM EST, Monday through Friday.",2025-01-15T11:00:10Z,,
```

### JSON Format

JSON files should contain either a top-level array of conversation objects or an object with one of these recognised keys: `conversations`, `data`, `results`, `items`.

**Example JSON:**

```json
[
  {
    "conversation_id": "conv-001",
    "started_at": "2025-01-15T10:00:00Z",
    "ended_at": "2025-01-15T10:05:00Z",
    "messages": [
      {"role": "user", "content": "How do I reset my password?", "timestamp": "2025-01-15T10:00:00Z"},
      {"role": "assistant", "content": "Go to Settings > Security > Reset Password.", "timestamp": "2025-01-15T10:00:15Z"}
    ]
  },
  {
    "conversation_id": "conv-002",
    "started_at": "2025-01-15T11:00:00Z",
    "ended_at": "2025-01-15T11:02:00Z",
    "messages": [
      {"role": "user", "content": "What are your hours?", "timestamp": "2025-01-15T11:00:00Z"},
      {"role": "assistant", "content": "We are open 9 AM to 5 PM EST.", "timestamp": "2025-01-15T11:00:10Z"}
    ]
  }
]
```

### JSONL Format

JSONL files contain one JSON conversation object per line. Each line uses the same structure as a single JSON conversation object.

**Example JSONL:**

```jsonl
{"conversation_id": "conv-001", "messages": [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi!"}], "started_at": "2025-01-15T10:00:00Z"}
{"conversation_id": "conv-002", "messages": [{"role": "user", "content": "Help"}, {"role": "assistant", "content": "Sure!"}], "started_at": "2025-01-15T11:00:00Z"}
```

### Validation

Before importing, you can validate a file to check for structural issues:

- **CSV:** Checks that required columns (`conversation_id`, `role`, `content`) are present.
- **JSON:** Checks that the root is an array or contains a recognised array key.
- **JSONL:** Checks that each of the first 10 lines is a valid JSON object.
- **General:** Verifies file existence, encoding, and that the extension matches the expected format.

### Importing via API

Use the conversation import endpoint to upload a JSON file:

```bash
curl -X POST "http://localhost:8000/api/v1/conversations/import?connector_id=CONNECTOR_UUID" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@conversations.json;type=application/json"
```

The endpoint accepts a JSON file upload and returns the list of created conversations.

### Additional Config

| Field           | Default | Description                         |
|-----------------|---------|-------------------------------------|
| `file_format`   | `json`  | File format: `csv`, `json`, `jsonl` |
| `encoding`      | `utf-8` | File character encoding             |
| `csv_delimiter`  | `,`     | Delimiter for CSV files             |
| `batch_size`    | 500     | Records per progress callback batch |
