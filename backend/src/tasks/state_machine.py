"""작업 상태 전이 규칙. I/O 없는 순수 함수.

판단(can_transition)과 예외 발생(InvalidTaskTransition)을 나눈 이유:
"어떤 전이가 가능한가"는 도표이고, "이 전이를 거부한다"는 비즈니스 결정이다.
후자는 service가 책임진다.
"""

from src.tasks.constants import TaskStatus

_ALLOWED: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    # 종결 상태에서는 어떤 전이도 허용하지 않는다. 이력은 append-only로만 남는다.
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def can_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    return to_status in _ALLOWED[from_status]
