r"""Security Input Validation, Sanitization, and Defense Engine.

Guards against:
- S3 Path Traversal / directory escapes (e.g. `..`, `/`, `\0`, `\`).
- DynamoDB injection via illegal table identifiers.
- Stored Cross-Site Scripting (XSS) via HTML entity encoding.
- JSON Bomb / Payload Depth exhaustion attacks.
"""

from __future__ import annotations

import html
import re
from typing import Any

from src.core.exceptions import ValidationError

# AWS DynamoDB table name constraint: 3-255 characters, [a-zA-Z0-9_.-]
DYNAMODB_TABLE_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{3,255}$")

# Maximum allowed payload dimensions to defeat Denial-of-Service resource exhaustion
MAX_PAYLOAD_DEPTH = 5
MAX_RECORDS_COUNT = 50000
MAX_RECORD_PAYLOAD_BYTES = 15 * 1024 * 1024  # 15 MB


def validate_s3_key(key: str) -> str:
    """Validates an S3 object key or prefix against directory traversal and illegal characters.

    Raises:
        ValidationError: If path traversal (..), null bytes, leading slashes, or backslashes are found.
    """
    if not key or not isinstance(key, str):
        raise ValidationError("S3 key must be a non-empty string.")

    # Reject null bytes (poison null byte attack)
    if "\0" in key:
        raise ValidationError("S3 key contains illegal null bytes.")

    # Reject Windows backslashes
    if "\\" in key:
        raise ValidationError("S3 key cannot contain backslashes.")

    # Reject path traversal tokens
    parts = key.split("/")
    for part in parts:
        if part in ("..", "."):
            raise ValidationError(f"S3 key '{key}' contains illegal path traversal token '{part}'.")

    # Reject leading slashes
    if key.startswith("/"):
        raise ValidationError(f"S3 key '{key}' cannot start with a leading slash.")

    return key


def validate_dynamodb_table_name(table_name: str) -> str:
    """Enforces AWS DynamoDB table name rules.

    Raises:
        ValidationError: If table name contains SQL injection, shell metacharacters, or illegal chars.
    """
    if not table_name or not isinstance(table_name, str):
        raise ValidationError("DynamoDB table name must be a non-empty string.")

    if not DYNAMODB_TABLE_PATTERN.match(table_name):
        raise ValidationError(
            f"Invalid DynamoDB table name '{table_name}'. "
            "Must be between 3 and 255 characters and contain only [a-zA-Z0-9_.-]."
        )
    return table_name


def sanitize_html(text: str) -> str:
    """Escapes HTML control characters (&, <, >, \", ') to neutralize stored XSS."""
    if not text or not isinstance(text, str):
        return text
    return html.escape(text.strip(), quote=True)


def validate_payload_depth(
    data: Any, max_depth: int = MAX_PAYLOAD_DEPTH, current_depth: int = 0
) -> None:
    """Recursively validates that nested dictionary/list depth does not exceed safety limits.

    Raises:
        ValidationError: If nesting depth exceeds max_depth (JSON bomb protection).
    """
    if current_depth > max_depth:
        raise ValidationError(
            f"Payload nesting depth ({current_depth}) exceeds maximum permitted safety limit ({max_depth})."
        )

    if isinstance(data, dict):
        for val in data.values():
            validate_payload_depth(val, max_depth, current_depth + 1)
    elif isinstance(data, (list, tuple, set)):
        for item in data:
            validate_payload_depth(item, max_depth, current_depth + 1)


def validate_payload_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validates record volume and nesting depth before staging or ingestion."""
    if not records or not isinstance(records, list):
        raise ValidationError("Payload data must be a non-empty list of dictionary records.")

    if len(records) > MAX_RECORDS_COUNT:
        raise ValidationError(
            f"Payload record count ({len(records)}) exceeds maximum batch limit ({MAX_RECORDS_COUNT})."
        )

    # Inspect structure and depth of each record
    for i, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValidationError(f"Record at index {i} must be a JSON dictionary object.")
        validate_payload_depth(record)

    return records
