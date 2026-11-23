# ADR 0004: Dual Authentication Architecture — JWT and API Keys

## Status
Accepted

## Date
2026-11-19

## Context
The AWS Cloud Workflow Orchestrator must support two distinct types of clients:
1. **Interactive Human Users**: DevOps engineers, system administrators, and migration leads interacting via the web-based React dashboard.
2. **Programmatic Machine Clients**: Automated CI/CD pipelines, external microservices, cron jobs, and CLI scripts triggering migrations headless.

A single authentication scheme cannot comfortably satisfy both:
- Using session cookies breaks headless CI/CD integrations.
- Using permanent static bearer tokens for web users introduces severe security vulnerabilities if intercepted.
- Passing raw API keys in browser sessions makes CSRF and token leakage harder to manage.

## Decision
We designed a **Dual Authentication and Role-Based Access Control (RBAC)** architecture:

1. **JWT (JSON Web Tokens) for Interactive Dashboard Users**:
   - **Access Tokens**: Short-lived (30 minutes), signed with HMAC-SHA256 (`HS256`), containing `sub` (user ID), `username`, and `role`.
   - **Refresh Tokens**: Long-lived (7 days), securely stored and exchanged via `/api/v1/auth/refresh` to renew expired access tokens seamlessly.
   - **Password Security**: Argon2 / Passlib bcrypt cryptographic hashing with automatic salt generation.
2. **API Keys for Programmatic Machine Clients**:
   - Generated with a recognizable prefix and high-entropy cryptographic random string: `wfo_live_<32_hex_chars>`.
   - Plaintext keys are shown **only once** upon creation.
   - Only the SHA-256 cryptographic digest of the API key is stored in PostgreSQL, preventing exposure even during database dumps.
   - Support for expiration dates, active/revoked status flags, and key rotation.
3. **Unified RBAC Layer**:
   - Three standardized roles: `admin`, `operator`, `viewer`.
   - FastAPI dependency injection (`get_current_active_user` and `require_role(...)`) transparently validates either `Authorization: Bearer <jwt>` or `X-API-Key: <key>`.

## Consequences

### Positive
- Unified security enforcement across human operators and automated CI/CD runners.
- Zero plaintext credential leakage: Lost or stolen database backups do not expose usable API keys or passwords.
- Fine-grained permission model prevents viewers from triggering destructive operations or modifying schedules.

### Negative / Trade-offs
- Requires maintaining two authentication middleware evaluation branches in the security layer.
- Clients must securely store and pass refresh tokens or rotating API keys.
