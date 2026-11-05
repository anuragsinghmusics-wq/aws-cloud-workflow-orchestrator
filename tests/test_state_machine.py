import pytest
from src.core.state_machine import WorkflowStateMachine, WorkflowState, InvalidStateTransitionError


def test_initial_state():
    fsm = WorkflowStateMachine()
    assert fsm.current_state == WorkflowState.PENDING
    assert not fsm.is_terminal()


def test_happy_path_transitions():
    fsm = WorkflowStateMachine()
    fsm.transition_to(WorkflowState.EXTRACTING)
    assert fsm.current_state == WorkflowState.EXTRACTING

    fsm.transition_to(WorkflowState.TRANSFORMING)
    assert fsm.current_state == WorkflowState.TRANSFORMING

    fsm.transition_to(WorkflowState.LOADING)
    assert fsm.current_state == WorkflowState.LOADING

    fsm.transition_to(WorkflowState.VERIFYING)
    assert fsm.current_state == WorkflowState.VERIFYING

    fsm.transition_to(WorkflowState.COMPLETED)
    assert fsm.current_state == WorkflowState.COMPLETED
    assert fsm.is_terminal()


def test_retry_loop_transition():
    fsm = WorkflowStateMachine(initial_state=WorkflowState.LOADING)
    fsm.transition_to(WorkflowState.RETRYING)
    assert fsm.current_state == WorkflowState.RETRYING

    fsm.transition_to(WorkflowState.LOADING)
    assert fsm.current_state == WorkflowState.LOADING


def test_invalid_transition_raises():
    fsm = WorkflowStateMachine(initial_state=WorkflowState.PENDING)
    with pytest.raises(InvalidStateTransitionError):
        fsm.transition_to(WorkflowState.COMPLETED)

