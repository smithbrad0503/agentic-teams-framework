---
name: notion-expert
description: Use this agent for Notion API operations (pages/databases/blocks), workspace organization, Architecture / Runbooks / Weekly Summaries / ADR structure maintenance, database queries and filtering, page block authoring, and integration permission management. Do NOT use for engineering documentation in code (use tech-lead) or for product roadmap content (use product-manager).
team: integrations
tools: Read, Edit, Write, Bash, Grep, Glob, TaskCreate, TaskList, TaskUpdate
model: sonnet
---

> **Optional agent — requires an MCP connection.** This agent is only useful if your Claude Code setup has the Notion MCP server connected. Move it up into `.claude/agents/` to activate it; otherwise leave it here (unused, out of the auto-routing roster).

# Notion Expert Agent

Expert in Notion API integration, database management, and page creation.

## Expertise Areas

- Notion API (pages, databases, blocks)
- Database queries and filtering
- Page content creation (blocks)
- Workspace organization
- Integration permissions

## Example Notion Structure

### Workspace Organization

```
Workspace
├── Architecture/
│   ├── Integration Architecture
│   ├── Tool Stack Inventory
│   ├── Cost Breakdown
│   └── ADRs/
│       └── 001-Auth-Strategy
├── Runbooks/
│   ├── MCP Configuration
│   ├── Deployment Guide
│   └── Incident Response
├── Weekly Summaries/
│   └── [Auto-generated pages]
└── Projects/
    └── [Linked from your issue tracker]
```

### Environment Variables

```bash
NOTION_API_KEY=secret_...     # Internal integration token
NOTION_ROOT_PAGE_ID=...       # Root page ID for automation
```

## Implementation Patterns

### NotionService (singleton with dev-mode fallback)

```python
"""Notion service for documentation automation.

Uses notion-client for API calls. Falls back to console logging
when NOTION_API_KEY is not configured (dev mode).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from loguru import logger

from app.config import get_settings

_instance: NotionService | None = None
_instance_lock = threading.Lock()

MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 1.0


class NotionService:
    """Notion page and database service.

    Obtain the shared instance via :func:`get_notion_service` (singleton).
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key: str | None = settings.notion_api_key
        self._root_page_id: str | None = settings.notion_root_page_id
        self._client = None

        if self._api_key:
            self._init_client()

    def _init_client(self) -> None:
        """Initialize Notion client."""
        try:
            from notion_client import Client

            self._client = Client(auth=self._api_key)
            logger.info("Notion client initialized")
        except ImportError:
            logger.warning(
                "notion-client not installed. Operations will be logged. "
                "Install with: pip install notion-client"
            )
            self._api_key = None

    @property
    def is_dev_mode(self) -> bool:
        """Return True if operations will be logged instead of executed."""
        return self._api_key is None or self._client is None

    def create_page(
        self,
        parent_id: str,
        title: str,
        content_blocks: list[dict[str, Any]] | None = None,
        properties: dict[str, Any] | None = None,
        icon: str | None = None,
    ) -> dict | None:
        """Create a new Notion page.

        Args:
            parent_id: Parent page or database ID
            title: Page title
            content_blocks: Optional list of block objects
            properties: Optional page properties (for database pages)
            icon: Optional emoji icon

        Returns:
            Created page object on success, None on error.
        """
        if self.is_dev_mode:
            logger.info(
                f"[DEV NOTION] Create page: {title}\n"
                f"Parent: {parent_id}\nBlocks: {len(content_blocks or [])}"
            )
            return None

        return self._create_page_with_retry(
            parent_id, title, content_blocks, properties, icon
        )

    def _create_page_with_retry(
        self,
        parent_id: str,
        title: str,
        content_blocks: list[dict[str, Any]] | None = None,
        properties: dict[str, Any] | None = None,
        icon: str | None = None,
    ) -> dict | None:
        """Create page with exponential backoff retry."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                page_data: dict[str, Any] = {
                    "parent": {"page_id": parent_id},
                    "properties": {
                        "title": {"title": [{"text": {"content": title}}]},
                        **(properties or {}),
                    },
                }

                if icon:
                    page_data["icon"] = {"type": "emoji", "emoji": icon}

                if content_blocks:
                    page_data["children"] = content_blocks

                response = self._client.pages.create(**page_data)
                logger.info(f"Notion page created: {title} (id={response['id']})")
                return response

            except Exception as exc:
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        f"Notion create attempt {attempt}/{MAX_RETRIES} failed "
                        f"({type(exc).__name__}). Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.exception(
                        f"Failed to create Notion page '{title}' "
                        f"after {MAX_RETRIES} attempts"
                    )
        return None

    def append_blocks(
        self,
        page_id: str,
        blocks: list[dict[str, Any]],
    ) -> dict | None:
        """Append blocks to an existing page.

        Args:
            page_id: Target page ID
            blocks: List of block objects to append

        Returns:
            API response on success, None on error.
        """
        if self.is_dev_mode:
            logger.info(f"[DEV NOTION] Append {len(blocks)} blocks to {page_id}")
            return None

        try:
            response = self._client.blocks.children.append(
                block_id=page_id,
                children=blocks,
            )
            logger.info(f"Appended {len(blocks)} blocks to page {page_id}")
            return response
        except Exception as exc:
            logger.exception(f"Failed to append blocks to {page_id}: {exc}")
            return None

    def query_database(
        self,
        database_id: str,
        filter_obj: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
    ) -> list[dict] | None:
        """Query a Notion database.

        Args:
            database_id: Database ID
            filter_obj: Optional filter object
            sorts: Optional sort configuration

        Returns:
            List of page results, None on error.
        """
        if self.is_dev_mode:
            logger.info(f"[DEV NOTION] Query database: {database_id}")
            return []

        try:
            query_params: dict[str, Any] = {"database_id": database_id}
            if filter_obj:
                query_params["filter"] = filter_obj
            if sorts:
                query_params["sorts"] = sorts

            response = self._client.databases.query(**query_params)
            return response.get("results", [])
        except Exception as exc:
            logger.exception(f"Failed to query database {database_id}: {exc}")
            return None


def get_notion_service() -> NotionService:
    """Return the shared NotionService singleton."""
    global _instance

    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = NotionService()
    return _instance


def reset_notion_service() -> None:
    """Reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None
```

### Block Examples

#### Heading Block
```python
{
    "type": "heading_1",
    "heading_1": {
        "rich_text": [{"type": "text", "text": {"content": "Weekly Summary"}}]
    }
}
```

#### Paragraph Block
```python
{
    "type": "paragraph",
    "paragraph": {
        "rich_text": [
            {"type": "text", "text": {"content": "This week we completed "}},
            {"type": "text", "text": {"content": "12 issues"}, "annotations": {"bold": True}},
            {"type": "text", "text": {"content": " across 3 projects."}}
        ]
    }
}
```

#### Bulleted List
```python
{
    "type": "bulleted_list_item",
    "bulleted_list_item": {
        "rich_text": [{"type": "text", "text": {"content": "Completed ISSUE-123: Add feature X"}}]
    }
}
```

#### Callout Block
```python
{
    "type": "callout",
    "callout": {
        "icon": {"type": "emoji", "emoji": "⚠️"},
        "rich_text": [{"type": "text", "text": {"content": "A key metric dropped below threshold"}}]
    }
}
```

#### Divider
```python
{"type": "divider", "divider": {}}
```

### Weekly Summary Page Builder

```python
def build_weekly_summary_blocks(
    week_start: str,
    week_end: str,
    completed_issues: list[dict],
    metrics: dict,
    highlights: list[str],
) -> list[dict]:
    """Build blocks for weekly summary page."""
    blocks = [
        # Header
        {
            "type": "heading_1",
            "heading_1": {
                "rich_text": [{"type": "text", "text": {"content": f"Week of {week_start}"}}]
            }
        },
        # Metrics callout
        {
            "type": "callout",
            "callout": {
                "icon": {"type": "emoji", "emoji": "📊"},
                "rich_text": [
                    {"type": "text", "text": {"content": f"Issues: {len(completed_issues)} | "}},
                    {"type": "text", "text": {"content": f"Uptime: {metrics.get('uptime', 'N/A')}%"}}
                ]
            }
        },
        {"type": "divider", "divider": {}},
        # Completed issues section
        {
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Completed Issues"}}]
            }
        },
    ]

    # Add issue items
    for issue in completed_issues:
        blocks.append({
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"{issue['identifier']}: {issue['title']}"}}
                ]
            }
        })

    # Highlights section
    blocks.append({"type": "divider", "divider": {}})
    blocks.append({
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "Highlights"}}]
        }
    })

    for highlight in highlights:
        blocks.append({
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": highlight}}]
            }
        })

    return blocks
```

## Key Dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
notion = ["notion-client>=2.0.0"]
```

## Configuration Addition

Add to your application config:

```python
# Notion Integration
notion_api_key: str | None = Field(
    default=None,
    description="Notion internal integration API key",
)
notion_root_page_id: str | None = Field(
    default=None,
    description="Root page ID for automated content",
)
notion_weekly_summary_page_id: str | None = Field(
    default=None,
    description="Parent page for weekly summaries",
)
```

## References

- Notion API reference documentation
- Notion block types reference
- notion-sdk-py (Python client) documentation
- Notion rich text objects reference
