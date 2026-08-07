from src.exceptions import NotFoundError


class ScheduleNotFound(NotFoundError):
    code = "schedule_not_found"
    message = "해당 반복 지시를 찾을 수 없습니다."
