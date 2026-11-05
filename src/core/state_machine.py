from enum import Enum
from typing import Dict, Set


class WorkflowState(str, Enum):
    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    TRANSFORMING = "TRANSFORMING"
    LOADING = "LOADING"
    RETRYING = "RETRYING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is requested."""
    pass


class WorkflowStateMachine:
    """
    Finite State Machine (FSM) enforcing deterministic, valid state transitions
    during migration and configuration workflows.
    """

    # Valid transitions mapping
    VALID_TRANSITIONS: Dict[WorkflowState, Set[WorkflowState]] = {
        WorkflowState.PENDING: {WorkflowState.EXTRACTING, WorkflowState.FAILED},
        WorkflowState.EXTRACTING: {WorkflowState.TRANSFORMING, WorkflowState.FAILED},
        WorkflowState.TRANSFORMING: {WorkflowState.LOADING, WorkflowState.FAILED},
        WorkflowState.LOADING: {WorkflowState.VERIFYING, WorkflowState.RETRYING, WorkflowState.FAILED},
        WorkflowState.RETRYING: {WorkflowState.LOADING, WorkflowState.FAILED},
        WorkflowState.VERIFYING: {WorkflowState.COMPLETED, WorkflowState.FAILED},
        WorkflowState.COMPLETED: set(),  # Terminal state
        WorkflowState.FAILED: {WorkflowState.PENDING},  # Can be re-enqueued
    }

    def __init__(self, initial_state: WorkflowState = WorkflowState.PENDING):
        self._current_state = initial_state

    @property
    def current_state(self) -> WorkflowState:
        return self._current_state

    def transition_to(self, new_state: WorkflowState) -> WorkflowState:
        """
        Transitions to the new state if allowed by transition rules.
        """
        allowed = self.VALID_TRANSITIONS.get(self._current_state, set())
        if new_state not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition from {self._current_state.value} to {new_state.value}. "
                f"Allowed target states: {[s.value for s in allowed]}"
            )
        self._current_state = new_state
        return self._current_state

    def is_terminal(self) -> bool:
        return self._current_state in {WorkflowState.COMPLETED, WorkflowState.FAILED}

