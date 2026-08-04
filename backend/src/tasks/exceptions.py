from src.exceptions import AppError, NotFoundError


class TaskNotFound(NotFoundError):
    code = "task_not_found"
    message = "해당 작업을 찾을 수 없습니다."


class InvalidTaskTransition(AppError):
    status_code = 409
    code = "invalid_task_transition"
    message = "허용되지 않는 작업 상태 전이입니다."


class EmployeeBusy(AppError):
    status_code = 409
    code = "employee_busy"
    message = "직원이 이미 다른 작업을 수행 중입니다."


class InvalidPaginationCursor(AppError):
    status_code = 400
    code = "invalid_pagination_cursor"
    message = "유효하지 않은 페이지네이션 커서입니다."
