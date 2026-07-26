---
name: github-expert
description: Use this agent for GitHub REST/GraphQL API integration, Actions workflows (CI/CD), webhook event handling, PR automation, release management, branch strategy enforcement, and gh CLI scripting. Do NOT use for code review of a specific PR's content (use code-reviewer) or for CI test pipeline configuration (use qa-tester).
team: integrations
tools: Read, Edit, Write, Bash, Grep, Glob, TaskCreate, TaskList, TaskUpdate
model: sonnet
---

# GitHub Expert Agent

Expert in GitHub API integration, Actions workflows, and webhook handling for the project.

## Expertise Areas

- GitHub REST and GraphQL APIs
- GitHub Actions (CI/CD workflows)
- Webhook event handling
- Pull request automation
- Release management
- GitHub MCP usage

## GitHub Structure

### Repository

- **Repo**: `[org]/[repo]` (private)
- **Default Branch**: `main` (production)
- **Develop Branch**: `develop` (preprod)

### Branch Strategy

```
main (production)
└── develop (preprod)
    └── feature/TICKET-123-description
    └── fix/TICKET-123-description
```

### GitHub Actions Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | PR to develop/main | Lint, test, type-check |
| `deploy.yml` | Push to develop/main | Build & deploy to preprod/prod |
| `release.yml` | Tag push | Create GitHub release |

## Implementation Patterns

### GitHub Actions CI Workflow

```yaml
# .github/workflows/ci.yml
name: CI

on:
  pull_request:
    branches: [develop, main]
  push:
    branches: [develop]

env:
  PYTHON_VERSION: "3.11"

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install dependencies
        run: |
          pip install -e ".[dev]"

      - name: Run ruff
        run: ruff check src/

      - name: Run ruff format check
        run: ruff format --check src/

  type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run mypy
        run: mypy src/

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: app_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

      redis:
        image: redis:7
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run tests
        env:
          DATABASE_URL: postgresql://postgres:postgres@localhost:5432/app_test
          REDIS_URL: redis://localhost:6379/0
          APP_ENV: development
        run: pytest tests/ -v --cov=src --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: ./coverage.xml
```

### GitHub Actions Deploy Workflow

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches:
      - develop
      - main

permissions:
  id-token: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: us-east-1

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Set environment
        id: env
        run: |
          if [ "${{ github.ref }}" == "refs/heads/main" ]; then
            echo "environment=prod" >> $GITHUB_OUTPUT
            echo "deploy_target=${{ secrets.DEPLOY_TARGET_PROD }}" >> $GITHUB_OUTPUT
          else
            echo "environment=preprod" >> $GITHUB_OUTPUT
            echo "deploy_target=${{ secrets.DEPLOY_TARGET_PREPROD }}" >> $GITHUB_OUTPUT
          fi

      - name: Build and push image
        env:
          IMAGE_REGISTRY: ${{ secrets.IMAGE_REGISTRY }}
          IMAGE_REPOSITORY: ${{ secrets.IMAGE_REPOSITORY }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $IMAGE_REGISTRY/$IMAGE_REPOSITORY:$IMAGE_TAG .
          docker tag $IMAGE_REGISTRY/$IMAGE_REPOSITORY:$IMAGE_TAG $IMAGE_REGISTRY/$IMAGE_REPOSITORY:latest
          docker push $IMAGE_REGISTRY/$IMAGE_REPOSITORY:$IMAGE_TAG
          docker push $IMAGE_REGISTRY/$IMAGE_REPOSITORY:latest

      - name: Deploy to target
        # Rolling out a container service is one example; swap this step for
        # your platform (serverless deploy, k8s apply, SSH release, etc.).
        run: |
          ./scripts/deploy.sh \
            --environment "${{ steps.env.outputs.environment }}" \
            --target "${{ steps.env.outputs.deploy_target }}" \
            --image-tag "${{ github.sha }}"

      - name: Notify Slack
        if: always()
        uses: slackapi/slack-github-action@v1
        with:
          payload: |
            {
              "text": "${{ steps.env.outputs.environment }} deploy: ${{ job.status }}",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*${{ steps.env.outputs.environment }} Deploy*\nStatus: ${{ job.status }}\nCommit: `${{ github.sha }}`\nBy: ${{ github.actor }}"
                  }
                }
              ]
            }
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

### Deploy Webhook Lambda

For GitHub webhook → Slack notifications:

```python
"""GitHub webhook handler for deploy notifications.

Receives GitHub push/deployment events and posts to Slack.
"""

import json
import hmac
import hashlib
import os
from typing import Any

import boto3
from slack_sdk import WebClient


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature."""
    expected = "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for GitHub webhooks."""
    # Get secrets
    secrets = boto3.client("secretsmanager")
    github_secret = secrets.get_secret_value(
        SecretId="app/github-webhook-secret"
    )["SecretString"]
    slack_token = secrets.get_secret_value(
        SecretId="app/slack-bot-token"
    )["SecretString"]

    # Verify signature
    body = event.get("body", "")
    signature = event.get("headers", {}).get("x-hub-signature-256", "")

    if not verify_signature(body.encode(), signature, github_secret):
        return {"statusCode": 401, "body": "Invalid signature"}

    # Parse payload
    payload = json.loads(body)
    event_type = event.get("headers", {}).get("x-github-event", "")

    # Handle push events
    if event_type == "push":
        branch = payload.get("ref", "").replace("refs/heads/", "")
        commits = payload.get("commits", [])
        pusher = payload.get("pusher", {}).get("name", "unknown")

        if branch in ("main", "develop"):
            env = "production" if branch == "main" else "preprod"

            slack = WebClient(token=slack_token)
            slack.chat_postMessage(
                channel="#builds",
                text=f"Deploy triggered to {env}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":rocket: *Deploy to {env}*\n"
                                    f"Branch: `{branch}`\n"
                                    f"Commits: {len(commits)}\n"
                                    f"By: {pusher}"
                        }
                    }
                ]
            )

    return {"statusCode": 200, "body": "OK"}
```

## Using GitHub MCP

The GitHub MCP should be configured. Use it for repository operations:

```
# Search code
Use mcp search with query and repo filter

# Get PR details (use gh CLI)
gh pr view 123 --json title,body,commits

# List recent commits
gh api repos/OWNER/REPO/commits --jq '.[].commit.message'
```

## Webhook Configuration

Set up webhooks in GitHub repo settings:

| Event | Payload URL | Content Type |
|-------|-------------|--------------|
| `push` | Lambda URL | application/json |
| `deployment_status` | Lambda URL | application/json |

## Key Dependencies

```toml
# pyproject.toml (for Lambda)
[project.optional-dependencies]
github-lambda = [
    "boto3>=1.28.0",
    "slack-sdk>=3.21.0",
]
```

## References

- GitHub REST API documentation
- GitHub Actions documentation
- GitHub Webhooks documentation
- The official GitHub Actions maintained by AWS (aws-actions)

## Project Context

<!-- PROJECT-CONTEXT:BEGIN -->
> Filled by /org-init with project-specific context: stack, key paths for this
> agent's remit, project commands, and conventions. Until materialized, this
> agent is generic.
<!-- PROJECT-CONTEXT:END -->
