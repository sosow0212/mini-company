import pytest

from src.tasks.constants import TaskStatus
from src.tasks.state_machine import can_transition


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (TaskStatus.QUEUED, TaskStatus.RUNNING),
        (TaskStatus.QUEUED, TaskStatus.CANCELLED),
        (TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
        (TaskStatus.RUNNING, TaskStatus.FAILED),
        (TaskStatus.RUNNING, TaskStatus.CANCELLED),
    ],
)
def test_can_transition_returns_true_for_allowed_transitions(
    from_status: TaskStatus, to_status: TaskStatus
) -> None:
    assert can_transition(from_status, to_status)


@pytest.mark.parametrize(
    "terminal", [TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED]
)
@pytest.mark.parametrize("to_status", list(TaskStatus))
def test_can_transition_returns_false_for_any_transition_out_of_terminal_states(
    terminal: TaskStatus, to_status: TaskStatus
) -> None:
    assert not can_transition(terminal, to_status)


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (TaskStatus.QUEUED, TaskStatus.QUEUED),
        (TaskStatus.QUEUED, TaskStatus.SUCCEEDED),  # 실행 없이 바로 성공할 수 없다
        (TaskStatus.RUNNING, TaskStatus.QUEUED),  # 되돌리기 없음
        (TaskStatus.RUNNING, TaskStatus.RUNNING),
    ],
)
def test_can_transition_returns_false_for_other_disallowed_transitions(
    from_status: TaskStatus, to_status: TaskStatus
) -> None:
    assert not can_transition(from_status, to_status)
