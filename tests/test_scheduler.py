"""Unit tests for the exponential backoff, jitter, and retry scheduler."""

import unittest
from unittest.mock import MagicMock

from src.core.scheduler import calculate_exponential_backoff, execute_with_retry


class TestSchedulerRetry(unittest.TestCase):
    """Verifies that exponential backoff with full jitter and retry logic behave reliably."""

    def test_calculate_exponential_backoff_bounds(self):
        for attempt in range(1, 6):
            delay = calculate_exponential_backoff(attempt, base_delay=0.1, max_delay=5.0)
            self.assertGreaterEqual(delay, 0.0)
            self.assertLessEqual(delay, min(5.0, 0.1 * (2**attempt)))

    def test_execute_with_retry_succeeds_first_attempt(self):
        op = MagicMock(return_value="SUCCESS")
        result = execute_with_retry(op, max_retries=3, base_delay=0.01)
        self.assertEqual(result, "SUCCESS")
        self.assertEqual(op.call_count, 1)

    def test_execute_with_retry_recovers_after_transient_failure(self):
        op = MagicMock(
            side_effect=[ValueError("Transient 1"), ValueError("Transient 2"), "RECOVERED"]
        )
        result = execute_with_retry(
            op,
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(ValueError,),
        )
        self.assertEqual(result, "RECOVERED")
        self.assertEqual(op.call_count, 3)

    def test_execute_with_retry_raises_when_retries_exhausted(self):
        op = MagicMock(side_effect=RuntimeError("Persistent outage"))
        with self.assertRaises(RuntimeError):
            execute_with_retry(
                op,
                max_retries=2,
                base_delay=0.01,
                retryable_exceptions=(RuntimeError,),
            )
        self.assertEqual(op.call_count, 3)  # Initial try + 2 retries


if __name__ == "__main__":
    unittest.main()
