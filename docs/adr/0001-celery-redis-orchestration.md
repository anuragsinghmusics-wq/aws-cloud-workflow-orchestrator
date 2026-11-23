# ADR 0001: Distributed Task Orchestration with Celery and Redis

## Status
Accepted

## Date
2026-11-18

## Context
The AWS Cloud Workflow Orchestrator executes multi-stage data migration pipelines (Extract -> Transform -> Load -> Verify) across distributed cloud systems. The initial architectural prototype relied on an in-memory `concurrent.futures.ThreadPoolExecutor`. 

However, in-memory thread pools suffer from severe operational limitations in production:
1. **Process Coupling**: Worker threads share memory and crash when the main web server restarts or crashes.
2. **Horizontal Scaling Limits**: Workloads are restricted to a single host machine's CPU and memory limits.
3. **No Task Persistence or ACK Guarantees**: Any task running during an ungraceful container restart is silently lost without retry or reclamation.
4. **No Backpressure or Priority Routing**: High-priority migrations cannot preempt bulk background syncs.

## Decision
We adopted **Celery 5.4+** backed by **Redis 7+** as the asynchronous task execution and message broker layer:
- **Broker & Results**: Redis acts as an in-memory transport broker providing sub-millisecond dispatch and task state tracking.
- **Priority Queues**: Tasks are categorized into four priority queues (`critical`, `high`, `normal`, `low`) mapped to Celery routing keys.
- **Task Pipelines**: Multi-phase workflow pipelines are executed via Celery task chains (`extract -> transform -> load -> verify`) with immutable canvas signatures.
- **Periodic Scheduling**: Celery Beat provides cron-style scheduling for recurring migration jobs and periodic zombie task reclamation.
- **Deduplication & Idempotency**: Tasks check deterministically generated UUIDv5 identifiers before execution, preventing redundant computations.

## Consequences

### Positive
- **Fault Isolation**: Web API nodes (FastAPI) and task workers (Celery) scale independently in distinct Docker containers.
- **Automatic Heartbeats & Zombie Recovery**: Stale or unresponsive workers are automatically detected; unacknowledged tasks are re-queued.
- **Observability**: Celery event streams can be monitored using Flower and custom Prometheus exporter gauges.
- **Graceful Shutdown**: Workers support `SIGTERM` / `SIGQUIT` warm shutdown, allowing in-flight chunks to flush before termination.

### Negative / Trade-offs
- Requires managing and monitoring Redis as an additional infrastructure dependency.
- Tasks must pass serializable parameters (JSON) rather than Python runtime objects or open database sessions.
- Requires periodic vacuuming of Celery result backend keys in Redis to prevent memory leaks.
