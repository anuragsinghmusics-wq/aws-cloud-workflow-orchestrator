"""Unit tests for the Circuit Breaker resilience pattern."""

import time
import unittest
from unittest.mock import MagicMock

from src.core.exceptions import CircuitBreakerOpenError
from src.core.scheduler import CircuitBreaker, CircuitState


class TestCircuitBreaker(unittest.TestCase):
    """Verifies that CircuitBreaker state transitions and fast-fail behavior hold."""

    def test_initial_state_closed(self):
        cb = CircuitBreaker(name="test-circuit", failure_threshold=3, recovery_timeout=0.1)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.consecutive_failures, 0)

    def test_successful_call_passes_through(self):
        cb = CircuitBreaker(name="test-circuit")
        op = MagicMock(return_value="OK")
        result = cb.call(op, "arg1", kw="val")
        self.assertEqual(result, "OK")
        op.assert_called_once_with("arg1", kw="val")
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_trips_to_open_after_threshold_failures(self):
        cb = CircuitBreaker(name="test-circuit", failure_threshold=3, recovery_timeout=10.0)
        op = MagicMock(side_effect=ValueError("Service down"))

        # 1st failure
        with self.assertRaises(ValueError):
            cb.call(op)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.consecutive_failures, 1)

        # 2nd failure
        with self.assertRaises(ValueError):
            cb.call(op)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.consecutive_failures, 2)

        # 3rd failure: trips breaker to OPEN
        with self.assertRaises(ValueError):
            cb.call(op)
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertEqual(cb.consecutive_failures, 3)

        # Subsequent call fast-fails with CircuitBreakerOpenError without invoking op
        op.reset_mock()
        with self.assertRaises(CircuitBreakerOpenError):
            cb.call(op)
        op.assert_not_called()

    def test_half_open_probe_recovers_to_closed(self):
        cb = CircuitBreaker(name="test-circuit", failure_threshold=2, recovery_timeout=0.05)
        op_fail = MagicMock(side_effect=RuntimeError("Fail"))

        # Trip to OPEN
        with self.assertRaises(RuntimeError):
            cb.call(op_fail)
        with self.assertRaises(RuntimeError):
            cb.call(op_fail)
        self.assertEqual(cb.state, CircuitState.OPEN)

        # Wait for recovery timeout to elapse
        time.sleep(0.06)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Successful probe call resets circuit to CLOSED
        op_success = MagicMock(return_value="Recovered!")
        result = cb.call(op_success)
        self.assertEqual(result, "Recovered!")
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.consecutive_failures, 0)

    def test_half_open_probe_failure_re_opens_circuit(self):
        cb = CircuitBreaker(name="test-circuit", failure_threshold=2, recovery_timeout=0.05)
        op_fail = MagicMock(side_effect=RuntimeError("Fail"))

        with self.assertRaises(RuntimeError):
            cb.call(op_fail)
        with self.assertRaises(RuntimeError):
            cb.call(op_fail)
        self.assertEqual(cb.state, CircuitState.OPEN)

        time.sleep(0.06)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Probe fails: immediately trips back to OPEN
        with self.assertRaises(RuntimeError):
            cb.call(op_fail)
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_manual_reset(self):
        cb = CircuitBreaker(name="test-circuit", failure_threshold=1)
        with self.assertRaises(RuntimeError):
            cb.call(MagicMock(side_effect=RuntimeError("error")))
        self.assertEqual(cb.state, CircuitState.OPEN)

        cb.reset()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.consecutive_failures, 0)


if __name__ == "__main__":
    unittest.main()
