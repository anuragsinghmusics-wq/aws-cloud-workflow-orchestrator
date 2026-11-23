"""Idempotency and deduplication engine for migration tasks.

Computes canonical SHA-256 signatures and deterministic UUIDv5 identifiers to guarantee
that re-submitting an identical migration payload will never trigger duplicate side-effects.
"""

import hashlib
import json
import uuid
from typing import Any


def compute_payload_checksum(payload_data: list[dict[str, Any]]) -> str:
    """Computes a deterministic SHA-256 digest of payload data with sorted keys."""
    canonical_json = json.dumps(
        payload_data,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def generate_deterministic_job_id(
    workflow_name: str,
    source_type: str,
    target_table: str,
    payload_data: list[dict[str, Any]],
) -> str:
    """Generates a reproducible UUIDv5 identifier based on migration parameters and payload hash.

    Identical inputs produce the identical UUIDv5 string.
    """
    payload_hash = compute_payload_checksum(payload_data)
    composite_key = f"{workflow_name}:{source_type}:{target_table}:{payload_hash}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, composite_key))
