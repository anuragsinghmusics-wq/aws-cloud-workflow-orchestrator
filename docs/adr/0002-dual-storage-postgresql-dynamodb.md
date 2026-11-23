# ADR 0002: Dual-Storage Strategy — PostgreSQL for Metadata & DynamoDB for Migrations

## Status
Accepted

## Date
2026-11-18

## Context
A cloud migration orchestrator handles two completely different categories of data:
1. **Application Control Plane**: Relational metadata including user accounts, hashed passwords, API keys, role-based access controls, granular step-by-step audit logs, cron schedules, and webhook endpoint configurations. This data requires strict ACID transactions, relational foreign key constraints, and relational querying.
2. **Migration Data Plane**: Large, heterogeneous customer data entities, schema-mapped transformation output, high-volume key-value records destined for target NoSQL tables, and staged payload blobs.

Attempting to store both categories in a single storage engine results in major compromises:
- Using only PostgreSQL causes high-volume migration writes (millions of records) to saturate the relational connection pool, bloat tables, and degrade UI/API performance.
- Using only DynamoDB makes relational queries, multi-table joins (e.g. users to API keys to audit logs), and schema migrations complex and costly.

## Decision
We implemented a **Dual-Storage Architecture**:
1. **PostgreSQL 16 (Relational Control Plane)**:
   - Governed by SQLAlchemy 2.0 (asyncio) and versioned with Alembic migrations.
   - Houses `users`, `api_keys`, `workflows`, `workflow_steps`, `audit_logs`, `schedules`, and `webhook_subscriptions`.
   - Guarantees strict transactional consistency and audit trail immutability.
2. **AWS S3 (Staging & Blob Storage)**:
   - Stages raw extracted payloads and intermediate JSON artifacts.
   - Computes SHA-256 cryptographic checksums before and after transformation to guarantee end-to-end data integrity.
   - Provides time-limited pre-signed URLs for payload inspection without exposing bucket credentials.
3. **Amazon DynamoDB (Target NoSQL Data Plane)**:
   - Houses migrated application datasets and high-speed key-value query tables.
   - Interfaced through `boto3` with automatic chunking (25 items per `BatchWriteItem`), backoff retries on `ProvisionedThroughputExceededException`, and conditional writes for idempotency.

## Consequences

### Positive
- Complete isolation between control plane API operations and high-throughput data loading.
- Optimized storage cost: Large payloads live cheaply in S3 rather than consuming expensive relational database disk space.
- Clean architectural boundary matching enterprise production environments.

### Negative / Trade-offs
- Requires orchestrating transactions across storage systems; handled via explicit state machine phases and compensating actions.
- Local development requires LocalStack to emulate S3 and DynamoDB alongside PostgreSQL.
