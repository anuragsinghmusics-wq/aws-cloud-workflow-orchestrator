"""Finite State Machine (FSM) enforcing deterministic, valid state transitions.

Thread-safe implementation with transition hooks, detailed execution timeline,
and strict invariant enforcement for cloud migration workflows.
"""

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.core.exceptions import InvalidStateTransitionError, TerminalStateError
from src.core.logger import get_logger

logger = get_logger(__name__)


class WorkflowState(str, Enum):
    """Governed phases of the migration workflow lifecycle."""

    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    TRANSFORMING = "TRANSFORMING"
    LOADING = "LOADING"
    RETRYING = "RETRYING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Type alias for transition callbacks
StateHook = Callable[[WorkflowState, WorkflowState, dict[str, Any] | None], None]


class WorkflowStateMachine:
    """Finite State Machine (FSM) enforcing deterministic, thread-safe state transitions.

    Guarantees:
    - Atomicity: State changes and history logs are guarded by a re-entrant lock.
    - Lifecycle Hooks: Supports on_exit and on_enter hooks per state.
    - Audit Trail: Captures timestamped transition events with metadata.
    """

    # Deterministic transition graph
    VALID_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
        WorkflowState.PENDING: {WorkflowState.EXTRACTING, WorkflowState.FAILED},
        WorkflowState.EXTRACTING: {WorkflowState.TRANSFORMING, WorkflowState.FAILED},
        WorkflowState.TRANSFORMING: {WorkflowState.LOADING, WorkflowState.FAILED},
        WorkflowState.LOADING: {
            WorkflowState.VERIFYING,
            WorkflowState.RETRYING,
            WorkflowState.FAILED,
        },
        WorkflowState.RETRYING: {WorkflowState.LOADING, WorkflowState.FAILED},
        WorkflowState.VERIFYING: {WorkflowState.COMPLETED, WorkflowState.FAILED},
        WorkflowState.COMPLETED: set(),  # Terminal state
        WorkflowState.FAILED: {WorkflowState.PENDING},  # Can be re-enqueued for retry
    }

    def __init__(
        self, initial_state: WorkflowState = WorkflowState.PENDING, workflow_id: str | None = None
    ):
        self._lock = threading.RLock()
        self._workflow_id = workflow_id
        self._current_state = initial_state
        self._on_enter_hooks: dict[WorkflowState, list[StateHook]] = {}
        self._on_exit_hooks: dict[WorkflowState, list[StateHook]] = {}
        self._history: list[dict[str, Any]] = [
            {
                "from_state": None,
                "to_state": initial_state.value,
                "timestamp": datetime.now(UTC).isoformat(),
                "metadata": {"note": "initial_state"},
            }
        ]

    @property
    def current_state(self) -> WorkflowState:
        with self._lock:
            return self._current_state

    @property
    def workflow_id(self) -> str | None:
        return self._workflow_id

    def can_transition_to(self, target_state: WorkflowState) -> bool:
        """Evaluates whether transitioning to the target state is permissible."""
        with self._lock:
            allowed = self.VALID_TRANSITIONS.get(self._current_state, set())
            return target_state in allowed

    def transition_to(
        self,
        new_state: WorkflowState,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowState:
        """Transitions to new_state if permitted, triggering hooks and recording audit history.

        Raises:
            TerminalStateError: If current state is terminal (and not re-enqueued from FAILED).
            InvalidStateTransitionError: If the proposed transition violates the FSM graph.
        """
        with self._lock:
            old_state = self._current_state

            if old_state == WorkflowState.COMPLETED:
                raise TerminalStateError(
                    f"Workflow is in terminal state '{old_state.value}' and cannot transition to '{new_state.value}'."
                )

            allowed = self.VALID_TRANSITIONS.get(old_state, set())
            if new_state not in allowed:
                raise InvalidStateTransitionError(
                    from_state=old_state.value,
                    to_state=new_state.value,
                    allowed_states=[s.value for s in allowed],
                )

            # Execute on_exit hooks for old state
            for hook in self._on_exit_hooks.get(old_state, []):
                try:
                    hook(old_state, new_state, metadata)
                except Exception as exc:
                    logger.error(
                        "Error in on_exit hook",
                        extra={
                            "from_state": old_state.value,
                            "to_state": new_state.value,
                            "error": str(exc),
                        },
                    )

            # State mutation
            self._current_state = new_state
            transition_record = {
                "from_state": old_state.value,
                "to_state": new_state.value,
                "timestamp": datetime.now(UTC).isoformat(),
                "metadata": metadata or {},
            }
            self._history.append(transition_record)

            # Execute on_enter hooks for new state
            for hook in self._on_enter_hooks.get(new_state, []):
                try:
                    hook(old_state, new_state, metadata)
                except Exception as exc:
                    logger.error(
                        "Error in on_enter hook",
                        extra={
                            "from_state": old_state.value,
                            "to_state": new_state.value,
                            "error": str(exc),
                        },
                    )

            logger.info(
                "Workflow state transition completed",
                extra={
                    "workflow_id": self._workflow_id,
                    "from_state": old_state.value,
                    "to_state": new_state.value,
                },
            )
            return self._current_state

    def add_on_enter_hook(self, state: WorkflowState, hook: StateHook) -> None:
        """Registers a callback invoked upon entering the given state."""
        with self._lock:
            self._on_enter_hooks.setdefault(state, []).append(hook)

    def add_on_exit_hook(self, state: WorkflowState, hook: StateHook) -> None:
        """Registers a callback invoked upon leaving the given state."""
        with self._lock:
            self._on_exit_hooks.setdefault(state, []).append(hook)

    def is_terminal(self) -> bool:
        """Returns True if the current state is terminal (COMPLETED or FAILED)."""
        with self._lock:
            return self._current_state in {WorkflowState.COMPLETED, WorkflowState.FAILED}

    def get_history(self) -> list[dict[str, Any]]:
        """Returns an immutable snapshot of all state transitions."""
        with self._lock:
            return list(self._history)
