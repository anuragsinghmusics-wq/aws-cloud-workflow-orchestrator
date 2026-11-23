# API Guide & Operational Examples

Interactive guide for the AWS Cloud Workflow Orchestrator REST API.

---

## 1. Authentication & API Keys

### User Registration
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "lead_devops",
    "email": "devops@example.com",
    "password": "SuperSecretPassword123!",
    "full_name": "DevOps Lead",
    "role": "operator"
  }'
```

### Log In
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=lead_devops&password=SuperSecretPassword123!"
```

### Refresh Token
```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<YOUR_REFRESH_TOKEN>"}'
```

### Create Machine API Key
```bash
curl -X POST http://localhost:8000/api/v1/auth/api-keys \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name": "ci-deployer", "expires_days": 90}'
```

---

## 2. Managing Migration Workflows

### Trigger Migration
```bash
curl -X POST http://localhost:8000/api/v1/workflows \
  -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "source_system": "legacy-postgres-users",
    "target_table": "production-users-dynamodb",
    "priority": "HIGH",
    "payload": [
      {"id": "usr_101", "name": "Alice Smith"},
      {"id": "usr_102", "name": "Bob Jones"}
    ]
  }'
```

### Inspect Workflow State
```bash
curl -X GET http://localhost:8000/api/v1/workflows/<WORKFLOW_ID> \
  -H "X-API-Key: <YOUR_API_KEY>"
```

### Cancel Active Workflow
```bash
curl -X POST http://localhost:8000/api/v1/workflows/<WORKFLOW_ID>/cancel \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Manual operator cancellation"}'
```

---

## 3. Webhooks & Subscriptions

### Register Webhook Endpoint
```bash
curl -X POST http://localhost:8000/api/v1/webhooks \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://ops.example.com/webhooks/receiver",
    "description": "Slack Alert Receiver",
    "secret": "webhook-secret-token",
    "events": ["workflow.completed", "workflow.failed"]
  }'
```

### Test Webhook Dispatch
```bash
curl -X POST http://localhost:8000/api/v1/webhooks/<WEBHOOK_ID>/test \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

---

## 4. Scheduled Jobs

### Create Cron Schedule
```bash
curl -X POST http://localhost:8000/api/v1/schedules \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "daily-users-sync",
    "cron_expression": "0 2 * * *",
    "source_system": "legacy-db",
    "target_table": "target-dynamodb",
    "priority": "NORMAL",
    "template_payload": {"batch_size": 500}
  }'
```

### Trigger Schedule On-Demand
```bash
curl -X POST http://localhost:8000/api/v1/schedules/<SCHEDULE_ID>/trigger \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

---

## 5. Dead Letter Queue & Export

### View Quarantined Records
```bash
curl -X GET "http://localhost:8000/api/v1/dlq?limit=20" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

### Replay Poison Pill Record
```bash
curl -X POST http://localhost:8000/api/v1/dlq/<MESSAGE_ID>/replay \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

### Export Workflows CSV
```bash
curl -X GET "http://localhost:8000/api/v1/export/workflows/csv?status=COMPLETED" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -o export.csv
```
