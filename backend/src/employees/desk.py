"""책상 배치. I/O 없는 순수 함수.

채용 API가 좌표를 요청에서 받지 않는 이유: 3D 좌표는 사용자가 알 바가 아니다.
"어디에 앉힐까"는 사무실 레이아웃의 문제이고, 그 규칙은 여기 한 곳에 있어야 한다.

**기존 직원을 재배치하지 않는다.** 한 명 채용할 때마다 전체를 균등 재배치하면 모든
아바타가 한꺼번에 움직여서, 화면을 보던 사람이 누가 누구인지 놓친다. 새 직원은 비어
있는 첫 자리에 앉는다.
"""

from src.employees.domain import DeskPosition

_SPACING = 2.0
_ROW_DEPTH = 2.5
_DESKS_PER_ROW = 5
# 좌표 비교 허용 오차. float 왕복(Mongo ↔ JSON)에서 정확히 같은 값이 보장되지 않는다.
_EPSILON = 1e-6


def desk_for_slot(slot: int) -> DeskPosition:
    """슬롯 번호 → 좌표. 중앙에서 좌우로 번갈아 퍼진다.

    0, +1, -1, +2, -2 … 순서를 쓰는 이유: 총원을 몰라도 대칭이 유지된다. 총원으로
    나누는 방식(`(i - (n-1)/2) * spacing`)은 인원이 바뀔 때마다 모든 좌표가 바뀐다.
    """
    row, column = divmod(slot, _DESKS_PER_ROW)
    step = (column + 1) // 2
    direction = 1 if column % 2 == 1 else -1
    # step이 0일 때 곱셈을 그대로 두면 -0.0이 나와 JSON에 그대로 실린다.
    return DeskPosition(
        x=0.0 if step == 0 else step * _SPACING * direction,
        y=0.0,
        z=0.0 if row == 0 else -row * _ROW_DEPTH,
    )


def next_free_desk(occupied: list[DeskPosition]) -> DeskPosition:
    """점유되지 않은 첫 자리. 해고로 생긴 빈자리를 다시 쓴다."""
    taken = [(desk.x, desk.z) for desk in occupied]
    slot = 0
    while True:
        candidate = desk_for_slot(slot)
        if not any(
            abs(x - candidate.x) < _EPSILON and abs(z - candidate.z) < _EPSILON for x, z in taken
        ):
            return candidate
        slot += 1
