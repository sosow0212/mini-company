from src.exceptions import AppError, NotFoundError


class EmployeeNotFound(NotFoundError):
    code = "employee_not_found"
    message = "해당 직원을 찾을 수 없습니다."


class EmployeeNameTaken(AppError):
    """이름이 신원이다(시드의 멱등 등록이 이름으로 판정한다). 중복을 허용하면
    화면에서 같은 이름 둘을 구분할 수 없고, 시드가 어느 쪽을 갱신할지도 정해지지 않는다.
    """

    status_code = 409
    code = "employee_name_taken"
    message = "같은 이름의 직원이 이미 있습니다."


class EmployeeAtWork(AppError):
    """작업 중인 직원은 해고하지 않는다.

    지우면 그 작업은 담당자가 없는 채로 RUNNING에 남고, 회수 루프(Phase 9)가
    직원을 찾지 못해 영원히 정리되지 않는다.
    """

    status_code = 409
    code = "employee_at_work"
    message = "작업 중인 직원은 해고할 수 없습니다. 작업을 먼저 마감하세요."
