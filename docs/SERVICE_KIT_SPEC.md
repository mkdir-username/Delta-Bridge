# Service Kit Specification

## Overview

Service Kit — JSON-рецепт для взаимодействия с конкретным сервисом через IoE HTTP Proxy (Layer 1). Выполняется клиентом. Сервер не меняется.

## Format

```json
{
  "service": "hackernews",
  "version": "1.0",
  "description": "Hacker News API",
  "auth": "none",
  "actions": {
    "top_stories": {
      "steps": [...]
    }
  }
}
```

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `service` | string | yes | Unique service identifier |
| `version` | string | yes | Kit version (semver) |
| `description` | string | no | Human-readable description |
| `auth` | string | yes | `"none"`, `"cookie"`, `"token"` |
| `actions` | object | yes | Map of action_name → action definition |

## Action Definition

```json
{
  "steps": [
    { "type": "http", ... },
    { "type": "extract", ... }
  ]
}
```

## Step Types

### `http` — HTTP request via IoE proxy

```json
{
  "type": "http",
  "method": "GET",
  "url": "https://api.example.com/endpoint/{param}",
  "headers": {},
  "body": null
}
```

URL supports `{param}` placeholders substituted from action params.

### `extract` — Extract data from previous step's response

```json
{
  "type": "extract",
  "source": "body",
  "path": "$.items[:10].id",
  "as": "item_ids"
}
```

| Field | Description |
|-------|-------------|
| `source` | `"body"` (response body) or `"headers"` |
| `path` | JSONPath expression or CSS selector |
| `as` | Variable name for extracted value |

### `condition` — Conditional execution

```json
{
  "type": "condition",
  "if": "{auth_status} == authorized",
  "then": [...],
  "else": [...]
}
```

### `loop` — Iterate over extracted array

```json
{
  "type": "loop",
  "over": "{item_ids}",
  "as": "id",
  "steps": [...]
}
```

## Auth Flows

### `none` — No authentication needed

### `cookie` — Cookie-based session
```json
{
  "auth": "cookie",
  "auth_config": {
    "login_action": "login",
    "session_id_field": "session_id"
  }
}
```

### `token` — Bearer token
```json
{
  "auth": "token",
  "auth_config": {
    "header": "Authorization",
    "prefix": "Bearer ",
    "token_param": "api_key"
  }
}
```

## Example: Hacker News

```json
{
  "service": "hackernews",
  "version": "1.0",
  "description": "Hacker News API",
  "auth": "none",
  "actions": {
    "top_stories": {
      "steps": [
        {
          "type": "http",
          "method": "GET",
          "url": "https://hacker-news.firebaseio.com/v0/topstories.json"
        },
        {
          "type": "extract",
          "source": "body",
          "path": "$[:10]",
          "as": "story_ids"
        }
      ]
    },
    "story_detail": {
      "steps": [
        {
          "type": "http",
          "method": "GET",
          "url": "https://hacker-news.firebaseio.com/v0/item/{id}.json"
        },
        {
          "type": "extract",
          "source": "body",
          "path": "$",
          "as": "story"
        }
      ]
    }
  }
}
```
