---
name: slack-expert
description: Use this agent for Slack Web API (posting messages, channel management), Events API webhook handling, Slack Bolt SDK for Python, interactive components (buttons, modals, menus), app manifests / OAuth, channel routing (#alerts, #builds, #general), and signing-secret verification. Do NOT use for marketing content drafted for Slack (use copywriter / marketing-expert).
team: integrations
tools: Read, Edit, Write, Bash, Grep, Glob, TaskCreate, TaskList, TaskUpdate
model: sonnet
---

> **Optional agent — requires an MCP connection.** This agent is only useful if your Claude Code setup has the Slack MCP server connected. Move it up into `.claude/agents/` to activate it; otherwise leave it here (unused, out of the auto-routing roster).

# Slack Expert Agent

Expert in Slack API integration, bot development, and webhook handling.

## Expertise Areas

- Slack Web API (posting messages, managing channels)
- Slack Events API (handling webhooks)
- Slack Bolt SDK for Python
- Interactive components (buttons, modals, menus)
- App manifests and OAuth configuration

## Example Slack Configuration

### Channels

| Channel | Purpose |
|---------|---------|
| `#alerts` | System alerts, warnings, incidents |
| `#builds` | CI/CD notifications, deployment status |
| `#general` | General discussion, announcements |

### Environment Variables

```bash
SLACK_API_TOKEN=xoxb-...      # Bot User OAuth Token
SLACK_SIGNING_SECRET=...       # For webhook verification
SLACK_APP_TOKEN=xapp-...       # For Socket Mode (optional)
```

## Implementation Patterns

### SlackService (singleton with dev-mode fallback)

```python
"""Slack service for notifications.

Uses slack-sdk for API calls. Falls back to console logging
when SLACK_API_TOKEN is not configured (dev mode).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from loguru import logger

from app.config import get_settings

_instance: SlackService | None = None
_instance_lock = threading.Lock()

MAX_SEND_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 1.0


class SlackService:
    """Slack messaging service.

    Obtain the shared instance via :func:`get_slack_service` (singleton).
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._api_token: str | None = settings.slack_api_token
        self._client = None

        if self._api_token:
            self._init_client()

    def _init_client(self) -> None:
        """Initialize Slack WebClient."""
        try:
            from slack_sdk import WebClient

            self._client = WebClient(token=self._api_token)
            logger.info("Slack client initialized")
        except ImportError:
            logger.warning(
                "slack-sdk not installed. Messages will be logged to console. "
                "Install with: pip install slack-sdk"
            )
            self._api_token = None

    @property
    def is_dev_mode(self) -> bool:
        """Return True if messages will be logged instead of sent."""
        return self._api_token is None or self._client is None

    def send_message(
        self,
        channel: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict | None:
        """Send a message to a Slack channel.

        Args:
            channel: Channel ID or name (e.g., "#alerts")
            text: Plain text message (fallback for notifications)
            blocks: Optional Block Kit blocks for rich formatting

        Returns:
            Slack API response on success, None in dev mode or on error.
        """
        if self.is_dev_mode:
            logger.info(
                f"[DEV SLACK] Channel: {channel} | Text: {text}\n"
                f"Blocks: {blocks or 'None'}"
            )
            return None

        return self._send_with_retry(channel, text, blocks)

    def _send_with_retry(
        self,
        channel: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict | None:
        """Send message with exponential backoff retry."""
        for attempt in range(1, MAX_SEND_RETRIES + 1):
            try:
                response = self._client.chat_postMessage(
                    channel=channel,
                    text=text,
                    blocks=blocks,
                )
                logger.info(f"Slack message sent to {channel}: ts={response['ts']}")
                return response.data
            except Exception as exc:
                if attempt < MAX_SEND_RETRIES:
                    delay = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        f"Slack send attempt {attempt}/{MAX_SEND_RETRIES} failed "
                        f"({type(exc).__name__}). Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.exception(
                        f"Failed to send Slack message to {channel} "
                        f"after {MAX_SEND_RETRIES} attempts"
                    )
        return None

    def send_alert(
        self,
        title: str,
        message: str,
        severity: str = "info",
        channel: str = "#alerts",
    ) -> dict | None:
        """Send a formatted alert message.

        Args:
            title: Alert title
            message: Alert details
            severity: One of "info", "warning", "error"
            channel: Target channel

        Returns:
            Slack API response on success, None otherwise.
        """
        emoji = {"info": ":information_source:", "warning": ":warning:", "error": ":x:"}
        color = {"info": "#36a64f", "warning": "#ff9800", "error": "#f44336"}

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji.get(severity, '')} {title}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
        ]

        return self.send_message(
            channel=channel,
            text=f"{title}: {message}",
            blocks=blocks,
        )


def get_slack_service() -> SlackService:
    """Return the shared SlackService singleton."""
    global _instance

    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SlackService()
    return _instance


def reset_slack_service() -> None:
    """Reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None
```

### Block Kit Examples

#### Simple Alert
```python
blocks = [
    {
        "type": "header",
        "text": {"type": "plain_text", "text": ":warning: Metric Alert"}
    },
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*A key metric* dropped below threshold\n"
                    "Current: *62%* | Threshold: *65%*"
        }
    },
    {
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": "Last updated: <!date^1234567890^{date_short_pretty}|fallback>"}
        ]
    }
]
```

#### Weekly Summary
```python
blocks = [
    {
        "type": "header",
        "text": {"type": "plain_text", "text": "Weekly Summary"}
    },
    {
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": "*Issues Completed*\n12"},
            {"type": "mrkdwn", "text": "*Deploys*\n8"},
            {"type": "mrkdwn", "text": "*API Uptime*\n99.9%"},
            {"type": "mrkdwn", "text": "*Requests Served*\n1,247"},
        ]
    },
    {"type": "divider"},
    {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*Key Accomplishments*\n- Completed ISSUE-123: Add feature X\n- Fixed ISSUE-456: Sync bug"}
    }
]
```

## Key Dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
slack = ["slack-sdk>=3.21.0"]
```

## Configuration Addition

Add to your application config:

```python
# Slack Integration
slack_api_token: str | None = Field(
    default=None,
    description="Slack Bot User OAuth Token (xoxb-...)",
)
slack_signing_secret: str | None = Field(
    default=None,
    description="Slack app signing secret for webhook verification",
)
slack_default_channel: str = Field(
    default="#alerts",
    description="Default channel for alerts",
)
```

## Testing

```python
import pytest
from unittest.mock import MagicMock, patch

from app.services.slack_service import (
    SlackService,
    get_slack_service,
    reset_slack_service,
)


@pytest.fixture(autouse=True)
def reset_service():
    reset_slack_service()
    yield
    reset_slack_service()


def test_dev_mode_logs_instead_of_sending(caplog):
    """In dev mode (no token), messages are logged."""
    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.slack_api_token = None
        service = get_slack_service()

        result = service.send_message("#test", "Hello")

        assert result is None
        assert "[DEV SLACK]" in caplog.text


def test_send_message_success():
    """Messages are sent via Slack API when configured."""
    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.slack_api_token = "xoxb-test"
        with patch("slack_sdk.WebClient") as mock_client:
            mock_client.return_value.chat_postMessage.return_value = MagicMock(
                data={"ok": True, "ts": "123.456"}
            )

            service = get_slack_service()
            result = service.send_message("#test", "Hello")

            assert result["ok"] is True
```

## References

- Slack Web API documentation
- Block Kit Builder
- slack-sdk for Python documentation
- Slack App Manifests reference
