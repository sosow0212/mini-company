from src.exceptions import NotFoundError


class EmployeeNotFound(NotFoundError):
    code = "employee_not_found"
    message = "해당 직원을 찾을 수 없습니다."
