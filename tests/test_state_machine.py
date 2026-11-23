"""Unit tests for the workflow finite state machine (FSM).

Compatible with both PyTest and standard Python unittest runner.
"""

import threading
import unittest

from src.core.exceptions import InvalidStateTransitionError, TerminalStateError
from src.core.state_machine import WorkflowState, WorkflowStateMachine


class TestWorkflowStateMachine(unittest.TestCase):
    """Verifies that finite state machine transitions, thread safety, and hooks hold."""

    def test_initial_state(self):
        fsm = WorkflowStateMachine()
        self.assertEqual(fsm.current_state, WorkflowState.PENDING)
        self.assertFalse(fsm.is_terminal())
        self.assertEqual(len(fsm.get_history()), 1)

    def test_happy_path_transitions(self):
        fsm = WorkflowStateMachine(workflow_id="wf-test-happy")
        fsm.transition_to(WorkflowState.EXTRACTING)
        self.assertEqual(fsm.current_state, WorkflowState.EXTRACTING)

        fsm.transition_to(WorkflowState.TRANSFORMING)
        self.assertEqual(fsm.current_state, WorkflowState.TRANSFORMING)

        fsm.transition_to(WorkflowState.LOADING)
        self.assertEqual(fsm.current_state, WorkflowState.LOADING)

        fsm.transition_to(WorkflowState.VERIFYING)
        self.assertEqual(fsm.current_state, WorkflowState.VERIFYING)

        fsm.transition_to(WorkflowState.COMPLETED)
        self.assertEqual(fsm.current_state, WorkflowState.COMPLETED)
        self.assertTrue(fsm.is_terminal())

        history = fsm.get_history()
        self.assertEqual(len(history), 6)
        self.assertEqual(history[-1]["to_state"], "COMPLETED")

    def test_retry_loop_transition(self):
        fsm = WorkflowStateMachine(initial_state=WorkflowState.LOADING)
        fsm.transition_to(WorkflowState.RETRYING)
        self.assertEqual(fsm.current_state, WorkflowState.RETRYING)

        fsm.transition_to(WorkflowState.LOADING)
        self.assertEqual(fsm.current_state, WorkflowState.LOADING)

    def test_invalid_transition_raises(self):
        fsm = WorkflowStateMachine(initial_state=WorkflowState.PENDING)
        with self.assertRaises(InvalidStateTransitionError):
            fsm.transition_to(WorkflowState.COMPLETED)

    def test_terminal_state_cannot_transition(self):
        fsm = WorkflowStateMachine(initial_state=WorkflowState.COMPLETED)
        with self.assertRaises(TerminalStateError):
            fsm.transition_to(WorkflowState.PENDING)

    def test_failed_state_can_re_enqueue(self):
        fsm = WorkflowStateMachine(initial_state=WorkflowState.FAILED)
        fsm.transition_to(WorkflowState.PENDING)
        self.assertEqual(fsm.current_state, WorkflowState.PENDING)

    def test_lifecycle_hooks(self):
        fsm = WorkflowStateMachine()
        events = []

        def on_exit_pending(old_state, new_state, meta):
            events.append(f"exit:{old_state.value}")

        def on_enter_extracting(old_state, new_state, meta):
            events.append(f"enter:{new_state.value}:{meta.get('user')}")

        fsm.add_on_exit_hook(WorkflowState.PENDING, on_exit_pending)
        fsm.add_on_enter_hook(WorkflowState.EXTRACTING, on_enter_extracting)

        fsm.transition_to(WorkflowState.EXTRACTING, metadata={"user": "Alice"})
        self.assertEqual(events, ["exit:PENDING", "enter:EXTRACTING:Alice"])

    def test_thread_safe_transitions(self):
        fsm = WorkflowStateMachine(initial_state=WorkflowState.LOADING)
        errors = []

        def attempt_transition(target):
            try:
                fsm.transition_to(target)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=attempt_transition, args=(WorkflowState.VERIFYING,))
        t2 = threading.Thread(target=attempt_transition, args=(WorkflowState.RETRYING,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one thread succeeds and the other gets an InvalidStateTransitionError
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], InvalidStateTransitionError)


if __name__ == "__main__":
    unittest.main()
