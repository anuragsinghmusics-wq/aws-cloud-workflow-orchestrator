"""Unit tests for the idempotency and deduplication engine."""

import unittest

from src.core.idempotency import compute_payload_checksum, generate_deterministic_job_id


class TestIdempotencyEngine(unittest.TestCase):
    """Verifies that payload hashing and UUIDv5 job deduplication are strictly deterministic."""

    def test_canonical_checksum_ignores_key_order(self):
        payload_1 = [{"user_id": "1", "name": "Alice", "score": 95}]
        payload_2 = [{"score": 95, "name": "Alice", "user_id": "1"}]

        hash_1 = compute_payload_checksum(payload_1)
        hash_2 = compute_payload_checksum(payload_2)
        self.assertEqual(hash_1, hash_2)

    def test_deterministic_job_id_reproducibility(self):
        payload = [
            {"id": "rec_001", "val": "A"},
            {"id": "rec_002", "val": "B"},
        ]
        id_1 = generate_deterministic_job_id(
            workflow_name="users-migration",
            source_type="POSTGRES",
            target_table="Dynamo_Users",
            payload_data=payload,
        )
        id_2 = generate_deterministic_job_id(
            workflow_name="users-migration",
            source_type="POSTGRES",
            target_table="Dynamo_Users",
            payload_data=payload,
        )
        self.assertEqual(id_1, id_2)
        self.assertEqual(len(id_1), 36)  # Standard UUID format

    def test_different_payload_produces_different_id(self):
        id_1 = generate_deterministic_job_id(
            workflow_name="migration-a",
            source_type="POSTGRES",
            target_table="Target",
            payload_data=[{"k": "v1"}],
        )
        id_2 = generate_deterministic_job_id(
            workflow_name="migration-a",
            source_type="POSTGRES",
            target_table="Target",
            payload_data=[{"k": "v2"}],
        )
        self.assertNotEqual(id_1, id_2)


if __name__ == "__main__":
    unittest.main()
