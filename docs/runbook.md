# Operational Runbook

Actionable steps for operating and troubleshooting the orchestrator system.

---

## 1. Circuit Breaker Activated

### Indicators
- API returns `503 Service Unavailable` with message indicating circuit breaker is `OPEN`.
- Logs indicate continuous throttling or network failure to downstream AWS endpoints.

### Remediation
1. Verify target AWS service status (e.g., check DynamoDB capacity units in AWS Console).
2. For DynamoDB: increase read/write capacity units or configure on-demand capacity mode.
3. Check health status via API:
   ```bash
   curl -s http://localhost:8000/api/v1/health | jq '.circuit_breakers'
   ```
4. The circuit breaker enters `HALF_OPEN` state after 30 seconds to probe recovery automatically.

---

## 2. High DLQ Volume

### Indicators
- Alert fired for quarantined message accumulation.
- Quarantined messages visible under `/api/v1/dlq`.

### Remediation
1. Query quarantined entries:
   ```bash
   curl -s http://localhost:8000/api/v1/dlq -H "Authorization: Bearer <TOKEN>"
   ```
2. Diagnose error cause (malformed input vs network timeout).
3. Once underlying issue is resolved, trigger replay:
   ```bash
   curl -X POST http://localhost:8000/api/v1/dlq/<MESSAGE_ID>/replay -H "Authorization: Bearer <TOKEN>"
   ```

---

## 3. Worker Node Scaling

### Indicators
- Celery queue depth accumulates under heavy migration load.
- Tasks stay in `PENDING` state longer than standard threshold.

### Remediation
Scale worker instances dynamically:
```bash
docker compose -f docker/docker-compose.prod.yml up -d --scale worker=4
```
