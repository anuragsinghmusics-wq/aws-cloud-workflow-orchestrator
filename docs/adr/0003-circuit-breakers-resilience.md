# ADR 0003: Circuit Breakers and Dead Letter Queue Resilience

## Status
Accepted

## Date
2026-11-19

## Context
Distributed migration systems frequently interact with remote cloud APIs that are susceptible to transient outages, network latency spikes, rate-limit throttling (e.g., DynamoDB capacity exhaustion), and malformed payloads.

Without resilience patterns:
1. Unchecked retries cause "retry storms" that amplify cloud provider outages and exhaust API rate limits.
2. Worker threads block indefinitely waiting on unresponsive remote services, cascading into thread starvation and system-wide degradation.
3. Corrupted or unprocessable records ("poison pills") cause perpetual task crashes, blocking the migration pipeline.

## Decision
We implemented a three-tier resilience architecture:
1. **Exponential Backoff with Full Jitter**:
   - Every remote cloud call employs randomized exponential backoff:
     $$\text{sleep} = \text{random}(0, \, \min(M, \, B \times 2^{\text{attempt}}))$$
   - Prevents synchronized wave retries across concurrent workers.
2. **Per-Service Circuit Breakers (`CircuitBreaker`)**:
   - Independent circuit breakers guard external AWS dependencies (`s3`, `dynamodb`, `cloudwatch`).
   - Three operational states:
     - `CLOSED`: Normal operations; tracks rolling failure counts.
     - `OPEN`: Tripped after consecutive threshold failures (default: 5); immediately fails fast with `CircuitBreakerError` without hitting the remote provider.
     - `HALF_OPEN`: Entered after recovery timeout (default: 30s); allows a single probe call to test service recovery before fully closing.
3. **Dead Letter Queue (DLQ) Quarantine Engine**:
   - Any record that repeatedly fails transformation or loading is quarantined in a dedicated DLQ repository.
   - DLQ entries record full diagnostic metadata: payload, target service, error classification, timestamp, retry count, and exception stack trace.
   - REST endpoints (`/api/v1/dlq`) allow administrators to inspect, purge, or manually replay quarantined messages once the underlying root cause is resolved.

## Consequences

### Positive
- Resilient self-healing architecture: System survives transient network hiccups and AWS service throttling.
- Fail-fast protection: Prevents resource exhaustion when downstream cloud services are offline.
- Zero data loss: Poison pills are isolated in the DLQ rather than discarded, enabling safe root-cause debugging and replay.

### Negative / Trade-offs
- Added complexity in error handling and state tracking.
- In `OPEN` state, all downstream tasks targeting that specific service fail immediately until the probe succeeds.
