"""Dead-Letter Queue (DLQ) & Quarantine Management Service.

Isolates poisoned or persistently failing records from production migration batches,
preventing pipeline stalls, enabling root-cause audit, and providing controlled replay mechanisms.
"""

from __future__ import annotations

import contextlib
import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import redis

from src.config import Settings, get_settings
from src.core.logger import get_logger
from src.core.metrics import metrics_registry

logger = get_logger(__name__)


@dataclass
class DeadLetterMessage:
    """Structure representing a quarantined failure item."""

    id: str
    job_id: str
    workflow_name: str
    source_type: str
    target_table: str
    payload: dict[str, Any]
    error_message: str
    error_type: str
    stack_trace: str | None
    retry_count: int
    quarantined_at: str
    status: str = "QUARANTINED"  # QUARANTINED, REPLAYED, DISCARDED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeadLetterMessage:
        return cls(**data)


class DeadLetterQueueService:
    """Thread-safe and Redis-backed Dead Letter Queue management."""

    def __init__(self, settings: Settings | None = None, redis_client: Any = None):
        self.settings = settings or get_settings()
        self._lock = threading.Lock()
        self._in_memory_store: dict[str, DeadLetterMessage] = {}
        self._redis_client = redis_client or self._init_redis()

    def _init_redis(self) -> redis.Redis | None:
        try:
            client = redis.from_url(
                self.settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
            )
            client.ping()
            return client
        except Exception as exc:
            logger.info(
                "Redis broker offline; DLQ operating with in-memory quarantine fallback",
                extra={"warning": str(exc)},
            )
            return None

    def quarantine_record(
        self,
        job_id: str,
        workflow_name: str,
        source_type: str,
        target_table: str,
        payload: dict[str, Any],
        error_message: str,
        error_type: str = "TaskExecutionError",
        stack_trace: str | None = None,
        retry_count: int = 3,
    ) -> DeadLetterMessage:
        """Quarantines a poisoned migration record into the dead-letter queue."""
        record_id = f"dlq-{uuid.uuid4()}"
        now_iso = datetime.now(UTC).isoformat()

        msg = DeadLetterMessage(
            id=record_id,
            job_id=job_id,
            workflow_name=workflow_name,
            source_type=source_type,
            target_table=target_table,
            payload=payload,
            error_message=error_message,
            error_type=error_type,
            stack_trace=stack_trace,
            retry_count=retry_count,
            quarantined_at=now_iso,
            status="QUARANTINED",
        )

        with self._lock:
            self._in_memory_store[record_id] = msg

        if self._redis_client:
            try:
                self._redis_client.hset(
                    f"dlq:record:{record_id}",
                    mapping={
                        "data": json.dumps(msg.to_dict()),
                        "job_id": job_id,
                        "status": "QUARANTINED",
                    },
                )
                self._redis_client.lpush("dlq:index", record_id)
            except Exception as exc:
                logger.warning(
                    "Failed writing DLQ message to Redis",
                    extra={"record_id": record_id, "error": str(exc)},
                )

        metrics_registry.records_failed_total.inc(amount=1.0)
        logger.warning(
            "Record quarantined into Dead Letter Queue",
            extra={
                "record_id": record_id,
                "job_id": job_id,
                "workflow_name": workflow_name,
                "error": error_message,
            },
        )
        return msg

    def list_quarantined(
        self,
        job_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DeadLetterMessage], int]:
        """Lists quarantined records with optional workflow_id and status filters."""
        with self._lock:
            all_records = list(self._in_memory_store.values())

        # If redis has records not in memory
        if self._redis_client:
            with contextlib.suppress(Exception):
                keys = self._redis_client.keys("dlq:record:*")
                for key in keys:
                    raw = self._redis_client.hget(key, "data")
                    if raw:
                        parsed = DeadLetterMessage.from_dict(json.loads(raw))
                        with self._lock:
                            self._in_memory_store[parsed.id] = parsed
                all_records = list(self._in_memory_store.values())

        # Apply filters
        filtered = [
            r
            for r in all_records
            if (not job_id or r.job_id == job_id) and (not status or r.status == status)
        ]

        total_count = len(filtered)
        # Sort newest first
        filtered.sort(key=lambda r: r.quarantined_at, reverse=True)
        paginated = filtered[offset : offset + limit]

        return paginated, total_count

    def get_quarantined(self, record_id: str) -> DeadLetterMessage | None:
        """Retrieves a single quarantined record by ID."""
        with self._lock:
            if record_id in self._in_memory_store:
                return self._in_memory_store[record_id]

        if self._redis_client:
            with contextlib.suppress(Exception):
                raw = self._redis_client.hget(f"dlq:record:{record_id}", "data")
                if raw:
                    parsed = DeadLetterMessage.from_dict(json.loads(raw))
                    with self._lock:
                        self._in_memory_store[record_id] = parsed
                    return parsed

        return None

    def replay_record(
        self,
        record_id: str,
        pipeline_executor: Any = None,
    ) -> DeadLetterMessage | None:
        """Replays a quarantined record by re-submitting it for processing."""
        msg = self.get_quarantined(record_id)
        if not msg:
            return None

        msg.status = "REPLAYED"
        with self._lock:
            self._in_memory_store[record_id] = msg

        if self._redis_client:
            with contextlib.suppress(Exception):
                self._redis_client.hset(
                    f"dlq:record:{record_id}",
                    mapping={"data": json.dumps(msg.to_dict()), "status": "REPLAYED"},
                )

        logger.info(
            "Quarantined record marked for replay",
            extra={"record_id": record_id, "job_id": msg.job_id},
        )

        if pipeline_executor:
            try:
                # In-process replay if pipeline executor is available
                pipeline_executor.execute_workflow(
                    job_id=f"{msg.job_id}-replay-{uuid.uuid4().hex[:6]}",
                    workflow_name=f"{msg.workflow_name}-replay",
                    payload_data=[msg.payload],
                    target_table=msg.target_table,
                    source_type=msg.source_type,
                )
            except Exception as exc:
                logger.error(
                    "Replay execution failed",
                    extra={"record_id": record_id, "error": str(exc)},
                )

        return msg

    def discard_record(self, record_id: str) -> bool:
        """Permanently marks a quarantined record as DISCARDED."""
        msg = self.get_quarantined(record_id)
        if not msg:
            return False

        msg.status = "DISCARDED"
        with self._lock:
            self._in_memory_store[record_id] = msg

        if self._redis_client:
            with contextlib.suppress(Exception):
                self._redis_client.hset(
                    f"dlq:record:{record_id}",
                    mapping={"data": json.dumps(msg.to_dict()), "status": "DISCARDED"},
                )

        logger.info("Quarantined record discarded", extra={"record_id": record_id})
        return True

    def reset_all(self) -> None:
        """Resets all records in memory and redis (for testing isolation)."""
        with self._lock:
            self._in_memory_store.clear()
        if self._redis_client:
            with contextlib.suppress(Exception):
                keys = self._redis_client.keys("dlq:*")
                if keys:
                    self._redis_client.delete(*keys)


# Global Singleton DLQ instance
dlq_service = DeadLetterQueueService()
