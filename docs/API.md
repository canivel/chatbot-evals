# API Reference

Base URL: `http://localhost:8000`

All API endpoints are prefixed with `/api/v1` except for health checks and documentation.

Interactive documentation is available at:
- **Swagger UI:** `/api/docs`
- **ReDoc:** `/api/redoc`
- **OpenAPI JSON:** `/api/openapi.json`

---

## Table of Contents

- [Authentication](#authentication)
- [Auth Endpoints](#auth-endpoints)
- [Connectors](#connectors)
- [Conversations](#conversations)
- [Evaluations](#evaluations)
- [Reports](#reports)
- [Health](#health)
- [Error Responses](#error-responses)

---

## Authentication

Most endpoints require a JWT Bearer token. Obtain one via `POST /api/v1/auth/login`.

Include the token in every request:

```
Authorization: Bearer <access_token>
```

Tokens expire after 60 minutes by default (configurable via `JWT_EXPIRATION` environment variable).

---

## Auth Endpoints

### POST /api/v1/auth/register

Create a new user account.

**Authentication:** None

**Request Body:**

```json
{
  "email": "user@example.com",
  "password": "securepassword123",
  "full_name": "Jane Doe",
  "organization_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

| Field             | Type        | Required | Description                                   |
|-------------------|-------------|----------|-----------------------------------------------|
| `email`           | string      | yes      | Valid email address                           |
| `password`        | string      | yes      | 8-128 characters                              |
| `full_name`       | string      | yes      | 1-255 characters                              |
| `organization_id` | uuid (null) | no       | Associate user with an existing organization  |

**Response:** `201 Created`

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "email": "user@example.com",
  "full_name": "Jane Doe",
  "is_active": true,
  "is_superuser": false,
  "organization_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-15T10:00:00Z"
}
```

**Error Codes:**

| Status | Detail                                |
|--------|---------------------------------------|
| 409    | A user with this email already exists |
| 404    | Organization not found                |
| 422    | Validation error                      |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "securepassword123",
    "full_name": "Jane Doe"
  }'
```

---

### POST /api/v1/auth/login

Authenticate with email and password to obtain a JWT access token.

**Authentication:** None

**Request Body:**

```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

| Field      | Type   | Required | Description    |
|------------|--------|----------|----------------|
| `email`    | string | yes      | Email address  |
| `password` | string | yes      | Password       |

**Response:** `200 OK`

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

**Error Codes:**

| Status | Detail                      |
|--------|-----------------------------|
| 401    | Incorrect email or password |
| 403    | Inactive user account       |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepassword123"}'
```

---

### GET /api/v1/auth/me

Return the profile of the currently authenticated user.

**Authentication:** Required (Bearer token)

**Response:** `200 OK`

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "email": "user@example.com",
  "full_name": "Jane Doe",
  "is_active": true,
  "is_superuser": false,
  "organization_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-15T10:00:00Z"
}
```

**Error Codes:**

| Status | Detail                                |
|--------|---------------------------------------|
| 401    | Missing or invalid credentials        |
| 403    | Inactive user account                 |

**curl example:**

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /api/v1/auth/organizations

Create a new organization and assign the current user to it. A random API key is generated automatically.

**Authentication:** Required (Bearer token)

**Request Body:**

```json
{
  "name": "Acme Inc.",
  "slug": "acme-inc"
}
```

| Field  | Type   | Required | Description                                         |
|--------|--------|----------|-----------------------------------------------------|
| `name` | string | yes      | Organization display name (1-255 chars)             |
| `slug` | string | yes      | URL-safe identifier (`^[a-z0-9\-]+$`, 1-255 chars) |

**Response:** `201 Created`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Acme Inc.",
  "slug": "acme-inc",
  "api_key": "xKj9_mN3pQ7rS1tU5vW8yA0bC2dE4fG6hI8jK0l",
  "settings": {},
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-15T10:00:00Z"
}
```

**Error Codes:**

| Status | Detail                                        |
|--------|-----------------------------------------------|
| 401    | Missing or invalid credentials                |
| 409    | An organization with this slug already exists |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/organizations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Inc.", "slug": "acme-inc"}'
```

---

## Connectors

All connector endpoints require authentication and an active organization. The user must belong to an organization (set via registration or org creation).

### GET /api/v1/connectors

List connectors for the current organization.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Default | Description               |
|-----------|------|---------|---------------------------|
| `skip`    | int  | 0       | Number of items to skip   |
| `limit`   | int  | 50      | Maximum items to return   |

**Response:** `200 OK`

```json
{
  "items": [
    {
      "id": "b1c2d3e4-f5a6-7890-bcde-f12345678901",
      "name": "Intercom Support",
      "connector_type": "intercom",
      "config": {"access_token": "***", "workspace_id": "abc123"},
      "organization_id": "550e8400-e29b-41d4-a716-446655440000",
      "is_active": true,
      "last_sync_at": "2025-01-15T12:00:00Z",
      "created_at": "2025-01-15T10:00:00Z",
      "updated_at": "2025-01-15T12:00:00Z"
    }
  ],
  "total": 1
}
```

**curl example:**

```bash
curl "http://localhost:8000/api/v1/connectors?skip=0&limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /api/v1/connectors

Create a new connector.

**Authentication:** Required

**Request Body:**

```json
{
  "name": "My Intercom Connector",
  "connector_type": "intercom",
  "config": {
    "access_token": "intercom-token-here",
    "workspace_id": "ws-123"
  },
  "is_active": true
}
```

| Field            | Type   | Required | Description                                        |
|------------------|--------|----------|----------------------------------------------------|
| `name`           | string | yes      | Human-readable name (1-255 chars)                  |
| `connector_type` | enum   | yes      | One of: `maven_agi`, `intercom`, `zendesk`, `webhook`, `rest_api`, `file_import` |
| `config`         | object | no       | Connector-specific configuration (see [Integrations](INTEGRATIONS.md)) |
| `is_active`      | bool   | no       | Whether the connector is active (default: true)    |

**Response:** `201 Created`

```json
{
  "id": "b1c2d3e4-f5a6-7890-bcde-f12345678901",
  "name": "My Intercom Connector",
  "connector_type": "intercom",
  "config": {"access_token": "intercom-token-here", "workspace_id": "ws-123"},
  "organization_id": "550e8400-e29b-41d4-a716-446655440000",
  "is_active": true,
  "last_sync_at": null,
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-15T10:00:00Z"
}
```

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/connectors \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Intercom Connector",
    "connector_type": "intercom",
    "config": {"access_token": "token", "workspace_id": "ws-123"}
  }'
```

---

### GET /api/v1/connectors/{connector_id}

Get a single connector by ID.

**Authentication:** Required

**Path Parameters:**

| Parameter      | Type | Description         |
|----------------|------|---------------------|
| `connector_id` | uuid | The connector UUID  |

**Response:** `200 OK` -- Same shape as the connector object in the list response.

**Error Codes:**

| Status | Detail              |
|--------|---------------------|
| 404    | Connector not found |

---

### PUT /api/v1/connectors/{connector_id}

Update one or more fields on a connector. Only provided fields are applied.

**Authentication:** Required

**Request Body:**

```json
{
  "name": "Renamed Connector",
  "config": {"access_token": "new-token"},
  "is_active": false
}
```

All fields are optional.

**Response:** `200 OK` -- The updated connector object.

---

### DELETE /api/v1/connectors/{connector_id}

Permanently delete a connector and its associated data.

**Authentication:** Required

**Response:** `204 No Content`

**Error Codes:**

| Status | Detail              |
|--------|---------------------|
| 404    | Connector not found |

**curl example:**

```bash
curl -X DELETE http://localhost:8000/api/v1/connectors/CONNECTOR_UUID \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /api/v1/connectors/{connector_id}/sync

Trigger an asynchronous data sync for the specified connector. The connector must be active.

**Authentication:** Required

**Response:** `200 OK` -- The connector object (confirming the sync request was accepted).

**Error Codes:**

| Status | Detail                           |
|--------|----------------------------------|
| 400    | Cannot sync an inactive connector |
| 404    | Connector not found              |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/connectors/CONNECTOR_UUID/sync \
  -H "Authorization: Bearer $TOKEN"
```

---

## Conversations

All conversation endpoints require authentication and an active organization.

### GET /api/v1/conversations

List conversations for the current organization, optionally filtered by connector.

**Authentication:** Required

**Query Parameters:**

| Parameter      | Type       | Default | Description                             |
|----------------|------------|---------|-----------------------------------------|
| `connector_id` | uuid (opt) | null    | Filter by connector                     |
| `skip`         | int        | 0       | Number of items to skip                 |
| `limit`        | int        | 50      | Maximum items to return                 |

**Response:** `200 OK`

```json
{
  "items": [
    {
      "id": "c1d2e3f4-a5b6-7890-cdef-123456789012",
      "external_id": "conv-001",
      "connector_id": "b1c2d3e4-f5a6-7890-bcde-f12345678901",
      "organization_id": "550e8400-e29b-41d4-a716-446655440000",
      "metadata": {"tags": ["support"]},
      "started_at": "2025-01-15T10:00:00Z",
      "ended_at": "2025-01-15T10:05:00Z",
      "message_count": 4,
      "created_at": "2025-01-15T10:00:00Z",
      "updated_at": "2025-01-15T10:05:00Z"
    }
  ],
  "total": 42
}
```

**curl example:**

```bash
curl "http://localhost:8000/api/v1/conversations?connector_id=CONNECTOR_UUID&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

---

### GET /api/v1/conversations/{conversation_id}

Get a single conversation with its message count.

**Authentication:** Required

**Response:** `200 OK` -- Same shape as a single conversation item.

**Error Codes:**

| Status | Detail                  |
|--------|-------------------------|
| 404    | Conversation not found  |

---

### GET /api/v1/conversations/{conversation_id}/messages

List all messages in a conversation, ordered by timestamp.

**Authentication:** Required

**Response:** `200 OK`

```json
[
  {
    "id": "d1e2f3a4-b5c6-7890-def1-234567890123",
    "conversation_id": "c1d2e3f4-a5b6-7890-cdef-123456789012",
    "role": "user",
    "content": "How do I reset my password?",
    "metadata": {},
    "timestamp": "2025-01-15T10:00:00Z"
  },
  {
    "id": "e1f2a3b4-c5d6-7890-ef12-345678901234",
    "conversation_id": "c1d2e3f4-a5b6-7890-cdef-123456789012",
    "role": "assistant",
    "content": "Go to Settings > Security > Reset Password.",
    "metadata": {},
    "timestamp": "2025-01-15T10:00:15Z"
  }
]
```

**Error Codes:**

| Status | Detail                  |
|--------|-------------------------|
| 404    | Conversation not found  |

**curl example:**

```bash
curl http://localhost:8000/api/v1/conversations/CONVERSATION_UUID/messages \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /api/v1/conversations/import

Import conversations from an uploaded JSON file. The file must contain a JSON array of conversation objects.

**Authentication:** Required

**Query Parameters:**

| Parameter      | Type | Required | Description            |
|----------------|------|----------|------------------------|
| `connector_id` | uuid | yes      | Target connector UUID  |

**Request:** `multipart/form-data` with a `file` field containing a JSON file.

**Expected JSON format:**

```json
[
  {
    "external_id": "conv-001",
    "metadata": {"source": "manual"},
    "messages": [
      {"role": "user", "content": "Hello"},
      {"role": "assistant", "content": "Hi there!"}
    ]
  }
]
```

**Response:** `201 Created`

```json
{
  "items": [
    {
      "id": "c1d2e3f4-a5b6-7890-cdef-123456789012",
      "external_id": "conv-001",
      "connector_id": "CONNECTOR_UUID",
      "organization_id": "ORG_UUID",
      "metadata": {"source": "manual"},
      "started_at": null,
      "ended_at": null,
      "message_count": 2,
      "created_at": "2025-01-15T10:00:00Z",
      "updated_at": "2025-01-15T10:00:00Z"
    }
  ],
  "total": 1
}
```

**Error Codes:**

| Status | Detail                                            |
|--------|---------------------------------------------------|
| 400    | Unsupported file type / connector_id required     |
| 422    | Invalid JSON file / not an array                  |

**curl example:**

```bash
curl -X POST "http://localhost:8000/api/v1/conversations/import?connector_id=CONNECTOR_UUID" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@conversations.json;type=application/json"
```

---

## Evaluations

All eval endpoints require authentication and an active organization.

### GET /api/v1/evals/metrics

List the catalogue of available evaluation metrics.

**Authentication:** None required (public endpoint)

**Response:** `200 OK`

```json
{
  "metrics": [
    {
      "name": "faithfulness",
      "description": "Measures whether the assistant's response is faithful to provided context",
      "category": "faithfulness",
      "version": "1.0.0"
    },
    {
      "name": "answer_relevance",
      "description": "Measures how relevant the assistant's answer is to the user's question",
      "category": "relevance",
      "version": "1.0.0"
    },
    {
      "name": "context_precision",
      "description": "Measures precision of retrieved context relative to ground truth",
      "category": "relevance",
      "version": "1.0.0"
    },
    {
      "name": "context_recall",
      "description": "Measures recall of retrieved context relative to ground truth",
      "category": "relevance",
      "version": "1.0.0"
    },
    {
      "name": "harmfulness",
      "description": "Detects potentially harmful or unsafe content in responses",
      "category": "safety",
      "version": "1.0.0"
    },
    {
      "name": "coherence",
      "description": "Evaluates logical coherence and clarity of the response",
      "category": "quality",
      "version": "1.0.0"
    },
    {
      "name": "response_completeness",
      "description": "Checks whether the response fully addresses the user's question",
      "category": "quality",
      "version": "1.0.0"
    }
  ]
}
```

**curl example:**

```bash
curl http://localhost:8000/api/v1/evals/metrics
```

---

### GET /api/v1/evals

List evaluation runs for the current organization.

**Authentication:** Required

**Query Parameters:**

| Parameter       | Type        | Default | Description                                  |
|-----------------|-------------|---------|----------------------------------------------|
| `status_filter` | enum (opt)  | null    | Filter by status: `pending`, `running`, `completed`, `failed` |
| `skip`          | int         | 0       | Number of items to skip                      |
| `limit`         | int         | 50      | Maximum items to return                      |

**Response:** `200 OK`

```json
{
  "items": [
    {
      "id": "f1a2b3c4-d5e6-7890-f123-456789012345",
      "name": "Q1 Faithfulness Eval",
      "organization_id": "550e8400-e29b-41d4-a716-446655440000",
      "connector_id": "b1c2d3e4-f5a6-7890-bcde-f12345678901",
      "config": {
        "metrics": ["faithfulness", "coherence"],
        "conversation_ids": null
      },
      "status": "completed",
      "started_at": "2025-01-15T10:00:00Z",
      "completed_at": "2025-01-15T10:15:00Z",
      "conversation_count": 100,
      "created_at": "2025-01-15T10:00:00Z",
      "updated_at": "2025-01-15T10:15:00Z"
    }
  ],
  "total": 5
}
```

**curl example:**

```bash
curl "http://localhost:8000/api/v1/evals?status_filter=completed&limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /api/v1/evals

Start a new evaluation run. The run is created with status `pending` and will be picked up by a background worker.

**Authentication:** Required

**Request Body:**

```json
{
  "name": "Weekly Quality Check",
  "connector_id": "b1c2d3e4-f5a6-7890-bcde-f12345678901",
  "metrics": ["faithfulness", "coherence", "answer_relevance"],
  "config": {
    "judge_model": "gpt-4o",
    "batch_size": 10
  },
  "conversation_ids": null
}
```

| Field              | Type         | Required | Description                                                 |
|--------------------|--------------|----------|-------------------------------------------------------------|
| `name`             | string       | yes      | Human-readable name (1-255 chars)                           |
| `connector_id`     | uuid (null)  | no       | Connector to pull conversations from                        |
| `metrics`          | string[]     | yes      | List of metric names to evaluate (min 1)                    |
| `config`           | object       | no       | Additional config (judge model, batch size, etc.)           |
| `conversation_ids` | uuid[] (null)| no       | Specific conversations to evaluate; null = all from connector |

**Response:** `201 Created`

```json
{
  "id": "f1a2b3c4-d5e6-7890-f123-456789012345",
  "name": "Weekly Quality Check",
  "organization_id": "550e8400-e29b-41d4-a716-446655440000",
  "connector_id": "b1c2d3e4-f5a6-7890-bcde-f12345678901",
  "config": {
    "metrics": ["faithfulness", "coherence", "answer_relevance"],
    "conversation_ids": null
  },
  "status": "pending",
  "started_at": null,
  "completed_at": null,
  "conversation_count": 0,
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-15T10:00:00Z"
}
```

**Error Codes:**

| Status | Detail                         |
|--------|--------------------------------|
| 400    | Unknown metrics: <list>        |
| 422    | Validation error               |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/evals \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Weekly Quality Check",
    "metrics": ["faithfulness", "coherence"],
    "connector_id": "CONNECTOR_UUID"
  }'
```

---

### GET /api/v1/evals/{eval_run_id}

Get details for a single evaluation run.

**Authentication:** Required

**Response:** `200 OK` -- Same shape as a single eval run item.

**Error Codes:**

| Status | Detail              |
|--------|---------------------|
| 404    | Eval run not found  |

---

### GET /api/v1/evals/{eval_run_id}/results

List evaluation results for a given run, optionally filtered by metric.

**Authentication:** Required

**Query Parameters:**

| Parameter     | Type        | Default | Description                   |
|---------------|-------------|---------|-------------------------------|
| `metric_name` | string (opt)| null    | Filter results by metric name |
| `skip`        | int         | 0       | Number of items to skip       |
| `limit`       | int         | 100     | Maximum items to return       |

**Response:** `200 OK`

```json
{
  "items": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "eval_run_id": "f1a2b3c4-d5e6-7890-f123-456789012345",
      "conversation_id": "c1d2e3f4-a5b6-7890-cdef-123456789012",
      "metric_name": "faithfulness",
      "score": 0.92,
      "explanation": "The response accurately reflects the provided context without introducing unsupported claims.",
      "details": {
        "sub_scores": {"accuracy": 0.95, "grounding": 0.89}
      },
      "created_at": "2025-01-15T10:05:00Z"
    }
  ],
  "total": 200
}
```

**curl example:**

```bash
curl "http://localhost:8000/api/v1/evals/EVAL_RUN_UUID/results?metric_name=faithfulness&limit=50" \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /api/v1/evals/{eval_run_id}/cancel

Cancel a pending or running evaluation run. Sets the status to `failed` and records the completion timestamp.

**Authentication:** Required

**Response:** `200 OK` -- The updated eval run object with `status: "failed"`.

**Error Codes:**

| Status | Detail                                           |
|--------|--------------------------------------------------|
| 400    | Cannot cancel eval run with status '<status>'    |
| 404    | Eval run not found                               |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/evals/EVAL_RUN_UUID/cancel \
  -H "Authorization: Bearer $TOKEN"
```

---

## Reports

All report endpoints require authentication and an active organization.

### GET /api/v1/reports/dashboard

Return high-level aggregate metrics across the entire organization, including counts of eval runs and conversations, and per-metric aggregate scores.

**Authentication:** Required

**Response:** `200 OK`

```json
{
  "organization_id": "550e8400-e29b-41d4-a716-446655440000",
  "eval_run_count": 12,
  "conversation_count": 1500,
  "aggregate_scores": [
    {
      "metric_name": "faithfulness",
      "mean": 0.8742,
      "median": 0.8742,
      "min": 0.45,
      "max": 1.0,
      "std_dev": 0.1234,
      "count": 3000
    },
    {
      "metric_name": "coherence",
      "mean": 0.9123,
      "median": 0.9123,
      "min": 0.65,
      "max": 1.0,
      "std_dev": 0.0876,
      "count": 3000
    }
  ]
}
```

**curl example:**

```bash
curl http://localhost:8000/api/v1/reports/dashboard \
  -H "Authorization: Bearer $TOKEN"
```

---

### GET /api/v1/reports/eval/{eval_run_id}

Generate a detailed report for a single evaluation run with per-metric aggregate statistics (mean, median, min, max, std_dev, count).

**Authentication:** Required

**Response:** `200 OK`

```json
{
  "eval_run_ids": ["f1a2b3c4-d5e6-7890-f123-456789012345"],
  "generated_at": "2025-01-15T12:00:00Z",
  "aggregate_scores": [
    {
      "metric_name": "faithfulness",
      "mean": 0.8742,
      "median": 0.88,
      "min": 0.45,
      "max": 1.0,
      "std_dev": 0.1234,
      "count": 100
    }
  ],
  "time_series": null,
  "comparison": null,
  "metadata": {}
}
```

**Error Codes:**

| Status | Detail                          |
|--------|---------------------------------|
| 404    | Eval run <id> not found         |

**curl example:**

```bash
curl http://localhost:8000/api/v1/reports/eval/EVAL_RUN_UUID \
  -H "Authorization: Bearer $TOKEN"
```

---

### GET /api/v1/reports/compare

Compare aggregate scores between two evaluation runs side by side.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Description         |
|-----------|------|----------|---------------------|
| `run_a`   | uuid | yes      | First eval run ID   |
| `run_b`   | uuid | yes      | Second eval run ID  |

**Response:** `200 OK`

```json
{
  "run_a_id": "f1a2b3c4-d5e6-7890-f123-456789012345",
  "run_b_id": "a9b8c7d6-e5f4-3210-9876-543210fedcba",
  "comparisons": [
    {
      "metric_name": "faithfulness",
      "run_a_score": 0.8742,
      "run_b_score": 0.9105,
      "delta": 0.0363,
      "percent_change": 4.15
    },
    {
      "metric_name": "coherence",
      "run_a_score": 0.9123,
      "run_b_score": 0.8954,
      "delta": -0.0169,
      "percent_change": -1.85
    }
  ]
}
```

**Error Codes:**

| Status | Detail                          |
|--------|---------------------------------|
| 404    | Eval run <id> not found         |

**curl example:**

```bash
curl "http://localhost:8000/api/v1/reports/compare?run_a=UUID_A&run_b=UUID_B" \
  -H "Authorization: Bearer $TOKEN"
```

---

### GET /api/v1/reports/trends

Return time-series data showing how metric scores evolve across evaluation runs.

**Authentication:** Required

**Query Parameters:**

| Parameter     | Type        | Default | Description                         |
|---------------|-------------|---------|-------------------------------------|
| `metric_name` | string (opt)| null    | Filter to a single metric           |
| `limit`       | int         | 30      | Number of most recent runs (max 365)|

**Response:** `200 OK`

```json
{
  "series": [
    {
      "metric_name": "faithfulness",
      "data_points": [
        {"timestamp": "2025-01-01T10:00:00Z", "value": 0.82},
        {"timestamp": "2025-01-08T10:00:00Z", "value": 0.85},
        {"timestamp": "2025-01-15T10:00:00Z", "value": 0.87}
      ]
    }
  ]
}
```

**curl example:**

```bash
curl "http://localhost:8000/api/v1/reports/trends?metric_name=faithfulness&limit=30" \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /api/v1/reports/export

Export evaluation data as a downloadable CSV or JSON file.

**Authentication:** Required

**Request Body:**

```json
{
  "eval_run_ids": ["f1a2b3c4-d5e6-7890-f123-456789012345"],
  "metrics": ["faithfulness", "coherence"],
  "format": "csv"
}
```

| Field          | Type         | Required | Description                                |
|----------------|--------------|----------|--------------------------------------------|
| `eval_run_ids` | uuid[]       | yes      | One or more eval run IDs to include (min 1)|
| `metrics`      | string[] (null)| no     | Subset of metrics; null = all              |
| `format`       | string       | no       | Output format: `json` (default), `csv`, or `pdf` |

**Response:** Streaming file download.

- **CSV:** `Content-Type: text/csv` with columns: `eval_run_id`, `conversation_id`, `metric_name`, `score`, `explanation`
- **JSON:** `Content-Type: application/json` with an array of result objects.

**Error Codes:**

| Status | Detail                            |
|--------|-----------------------------------|
| 400    | Unsupported export format         |
| 404    | Eval run <id> not found           |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/reports/export \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"eval_run_ids": ["EVAL_RUN_UUID"], "format": "csv"}' \
  -o report.csv
```

---

## Health

### GET /health

Simple health check endpoint. Does not require authentication.

**Response:** `200 OK`

```json
{
  "status": "ok"
}
```

**curl example:**

```bash
curl http://localhost:8000/health
```

---

## Error Responses

All error responses follow a consistent format:

```json
{
  "detail": "Human-readable error description"
}
```

### Common HTTP Status Codes

| Status | Meaning                                                         |
|--------|-----------------------------------------------------------------|
| 200    | Success                                                         |
| 201    | Resource created                                                |
| 204    | Success, no content (e.g. delete)                               |
| 400    | Bad request (invalid parameters or business rule violation)     |
| 401    | Unauthorized (missing or invalid JWT)                           |
| 403    | Forbidden (inactive account, no org, insufficient privileges)   |
| 404    | Resource not found                                              |
| 409    | Conflict (duplicate email, slug, etc.)                          |
| 422    | Validation error (invalid request body)                         |
| 500    | Internal server error                                           |

### Validation Errors (422)

Validation errors return additional detail about which fields failed:

```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    }
  ]
}
```
