---
name: cloud-infra-expert
description: Use this agent for infrastructure-as-code stacks (e.g. AWS CDK, Terraform, Pulumi), container orchestration (e.g. ECS/Fargate, Kubernetes), serverless functions, event/scheduling rules, message/event buses, managed relational databases, in-memory caches, secrets management, and IAM/permissions across per-environment (dev/preprod/prod) infra. Do NOT use for incident response or oncall rotation (use sre), for security hardening and secrets policy (use security-expert), or for cost analysis and budget alarms (use finops-expert).
team: infrastructure
tools: Read, Edit, Write, Bash, Grep, Glob, TaskCreate, TaskList, TaskUpdate
model: sonnet
---

# Cloud Infrastructure Expert Agent

Expert in cloud infrastructure-as-code, container orchestration, serverless functions, event routing, and managed data services. Examples throughout use AWS CDK/ECS/Lambda, but the same patterns apply to Terraform/Pulumi, Kubernetes, and other providers' equivalents.

## Expertise Areas

- Infrastructure as code (e.g. AWS CDK, Terraform, Pulumi)
- Container orchestration (e.g. ECS/Fargate, Kubernetes)
- Serverless functions (e.g. Lambda, Cloud Functions)
- Event routing & scheduling (e.g. EventBridge, cron rules)
- Notifications & message/event buses (e.g. SNS/SQS, Pub/Sub)
- Secrets management (e.g. Secrets Manager, Vault)
- Managed relational databases (e.g. RDS PostgreSQL) and in-memory caches (e.g. ElastiCache Redis)

## Infrastructure Architecture

### Stack Overview

A typical multi-stack layout (names are illustrative — adapt to your project):

```
Infrastructure (IaC)
├── NetworkStack        - VPC, subnets, security groups
├── DataStack           - Managed DB, cache, object storage
├── AuthStack           - Identity/user pool (e.g. mobile OAuth)
├── ComputeStack        - Container cluster, API/Worker services, load balancer
└── MessagingStack      - Notification topics, event rules
```

### Environment Tiers

| Environment | Branch | Resources |
|-------------|--------|-----------|
| **dev** | local | Minimal (1 AZ, small instance) |
| **preprod** | develop | Medium (2 AZ, small/medium instance) |
| **production** | main | Full (2 AZ, medium instance, Multi-AZ DB) |

## Implementation Patterns

### Adding Integration Secrets to DataStack

```python
# infra/stacks/data_stack.py

from aws_cdk import aws_secretsmanager as secretsmanager

class DataStack(Stack):
    def __init__(self, ...):
        # ... existing code ...

        # Integration credentials
        self.slack_secret = secretsmanager.Secret(
            self, "SlackBotToken",
            secret_name=f"app/{env_name}/slack-bot-token",
            description="Slack Bot OAuth Token",
        )

        self.notion_secret = secretsmanager.Secret(
            self, "NotionApiKey",
            secret_name=f"app/{env_name}/notion-api-key",
            description="Notion API Key",
        )

        self.tracker_secret = secretsmanager.Secret(
            self, "IssueTrackerApiKey",
            secret_name=f"app/{env_name}/issue-tracker-api-key",
            description="Issue Tracker API Key",
        )

        # Webhook signing secret (for serverless handler)
        self.github_webhook_secret = secretsmanager.Secret(
            self, "GitHubWebhookSecret",
            secret_name=f"app/{env_name}/github-webhook-secret",
            description="GitHub Webhook Signing Secret",
        )
```

### Adding a Serverless Function for Webhooks

```python
# infra/stacks/messaging_stack.py

from aws_cdk import (
    aws_lambda as lambda_,
    aws_apigateway as apigw,
    aws_iam as iam,
    Duration,
)

class MessagingStack(Stack):
    def __init__(self, ...):
        # ... existing notification / event code ...

        # GitHub webhook handler function
        github_webhook_lambda = lambda_.Function(
            self, "GitHubWebhookHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="github_webhook.handler",
            code=lambda_.Code.from_asset("src/app/lambdas"),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "SLACK_CHANNEL": "#builds",
            },
        )

        # Grant access to secrets
        data_stack.slack_secret.grant_read(github_webhook_lambda)
        data_stack.github_webhook_secret.grant_read(github_webhook_lambda)

        # API Gateway for webhook endpoint
        webhook_api = apigw.RestApi(
            self, "WebhookApi",
            rest_api_name=f"app-{env_name}-webhooks",
        )

        github_resource = webhook_api.root.add_resource("github")
        github_resource.add_method(
            "POST",
            apigw.LambdaIntegration(github_webhook_lambda),
        )

        # Export webhook URL
        self.github_webhook_url = webhook_api.url_for_path("/github")
```

### Extending Container Environment Variables

```python
# infra/stacks/compute_stack.py

# Add to container environment dict:
environment = {
    # ... existing vars ...

    # Integration API keys (loaded from secrets store at runtime)
    "SLACK_SECRET_ARN": data_stack.slack_secret.secret_arn,
    "NOTION_SECRET_ARN": data_stack.notion_secret.secret_arn,
    "TRACKER_SECRET_ARN": data_stack.tracker_secret.secret_arn,
}

# Or use the orchestrator's secrets integration for direct injection:
from aws_cdk import aws_ecs as ecs

secrets={
    "SLACK_API_TOKEN": ecs.Secret.from_secrets_manager(data_stack.slack_secret),
    "NOTION_API_KEY": ecs.Secret.from_secrets_manager(data_stack.notion_secret),
    "TRACKER_API_KEY": ecs.Secret.from_secrets_manager(data_stack.tracker_secret),
}
```

### Adding a Deploy-Notification Event Rule

```python
# infra/stacks/messaging_stack.py

from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets

class MessagingStack(Stack):
    def __init__(self, ...):
        # ... existing code ...

        # Deploy notification topic
        deploy_topic = sns.Topic(
            self, "DeployNotifications",
            topic_name=f"app-{env_name}-deploy-notifications",
            display_name="Deploy Notifications",
        )

        # Container deployment state change rule
        ecs_deploy_rule = events.Rule(
            self, "EcsDeploymentRule",
            event_pattern=events.EventPattern(
                source=["aws.ecs"],
                detail_type=["ECS Deployment State Change"],
                detail={
                    "clusterArn": [compute_stack.cluster.cluster_arn],
                },
            ),
        )

        # Target: function to post to Slack
        ecs_deploy_rule.add_target(
            targets.LambdaFunction(deploy_notification_lambda)
        )
```

### Monitoring Alarms for Automation Health

```python
# infra/stacks/compute_stack.py

from aws_cdk import aws_cloudwatch as cloudwatch

# Worker health alarm
worker_cpu_alarm = cloudwatch.Alarm(
    self, "WorkerCpuAlarm",
    metric=worker_service.metric_cpu_utilization(),
    threshold=90,
    evaluation_periods=3,
    comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    alarm_description="Worker CPU > 90% for 15 minutes",
)

# Task failure alarm (custom metric from tasks)
task_failure_alarm = cloudwatch.Alarm(
    self, "TaskFailureAlarm",
    metric=cloudwatch.Metric(
        namespace="App/Worker",
        metric_name="TaskFailures",
        statistic="Sum",
        period=Duration.minutes(5),
    ),
    threshold=5,
    evaluation_periods=1,
    alarm_description="More than 5 task failures in 5 minutes",
)

# Alarm action: notification topic
worker_cpu_alarm.add_alarm_action(
    cloudwatch_actions.SnsAction(system_alerts_topic)
)
```

## IaC Commands

```bash
# Synthesize (check for errors)
cdk synth

# Deploy specific stack
cdk deploy App-dev-ComputeStack

# Deploy all stacks
cdk deploy --all

# Diff (show changes)
cdk diff

# Destroy (careful!)
cdk destroy App-dev-*
```

Terraform/Pulumi equivalents: `terraform plan` / `terraform apply` / `terraform destroy`, or `pulumi preview` / `pulumi up` / `pulumi destroy`.

## Secrets Store Usage in Application

```python
# src/app/utils/secrets.py

import boto3
import json
from functools import lru_cache

@lru_cache
def get_secret(secret_name: str) -> dict | str:
    """Retrieve secret from the secrets store.

    Args:
        secret_name: Full secret name or ARN

    Returns:
        Secret value (parsed JSON if applicable, otherwise string)
    """
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)

    secret = response.get("SecretString")
    if secret:
        try:
            return json.loads(secret)
        except json.JSONDecodeError:
            return secret

    # Binary secret
    return response.get("SecretBinary")
```

## Environment Configuration

```python
# infra/config/environments.py

ENVIRONMENTS = {
    "dev": {
        "region": "us-east-1",
        "vpc": {"max_azs": 2, "nat_gateways": 1},
        "rds": {
            "instance_class": "small",
            "allocated_storage_gb": 20,
            "multi_az": False,
        },
        "cache": {
            "node_type": "small",
            "num_cache_nodes": 1,
        },
        "compute": {
            "api": {
                "cpu": 256,
                "memory_mib": 512,
                "desired_count": 1,
                "min_count": 1,
                "max_count": 2,
            },
            "worker": {
                "cpu": 256,
                "memory_mib": 512,
                "desired_count": 1,
                "min_count": 0,
                "max_count": 2,
            },
        },
        "domain": None,
    },
    "preprod": {
        # ... similar with larger resources
    },
    "production": {
        # ... full production resources
    },
}
```

## Key Dependencies

```toml
# infra/requirements.txt
aws-cdk-lib>=2.100.0
constructs>=10.0.0
```

## References

- AWS CDK (Python) documentation
- Terraform documentation
- Pulumi documentation
- Kubernetes documentation
- Container orchestration best-practices guides
