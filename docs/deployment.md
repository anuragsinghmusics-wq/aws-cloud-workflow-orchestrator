# Deployment and Operations Guide

Guidelines for deploying the orchestrator across staging and production infrastructure.

---

## 1. Prerequisites

- Linux host (Ubuntu 22.04 LTS or Amazon Linux 2023)
- Docker Engine 24.0+ & Docker Compose v2.20+
- Minimum hardware: 2 vCPUs, 4GB RAM (Staging), 4 vCPUs, 8GB RAM (Production)

---

## 2. Configuration Parameters

Configure environment settings in `.env`:

```bash
# General
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=replace-with-64-character-entropy-secret
API_V1_PREFIX=/api/v1

# Storage & Database
POSTGRES_SERVER=postgres
POSTGRES_PORT=5432
POSTGRES_USER=workflow_admin
POSTGRES_PASSWORD=production_secure_db_password_here
POSTGRES_DB=workflow_orchestrator
DATABASE_URL=postgresql+asyncpg://workflow_admin:production_secure_db_password_here@postgres:5432/workflow_orchestrator

# Message Broker
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_URL=redis://redis:6379/0

# Cloud Infrastructure
AWS_REGION=us-east-1
S3_PAYLOAD_BUCKET=prod-orchestrator-payloads
DYNAMODB_TABLE_NAME=prod-orchestrator-target
CLOUDWATCH_NAMESPACE=Production/WorkflowOrchestrator
```

---

## 3. Production Deployment with Docker Compose

The production stack runs via `docker/docker-compose.prod.yml`:
- **Nginx**: Gateway with TLS termination, Brotli compression, rate limiting.
- **API**: Gunicorn cluster running Uvicorn ASGI workers.
- **Worker**: Celery multi-worker daemon with priority queue consumers.
- **Beat**: Celery Beat scheduler for recurring tasks and zombie task cleanup.
- **Database**: PostgreSQL 16 with volume persistence.
- **Redis**: In-memory broker with AOF persistence.
- **Monitoring**: Prometheus and Grafana.

### Launch Containers
```bash
docker compose -f docker/docker-compose.prod.yml up -d --build
```

### Apply Database Migrations
```bash
docker compose -f docker/docker-compose.prod.yml exec api alembic upgrade head
```

### Check Service Health
```bash
curl -k https://localhost/api/v1/health/readiness
```
