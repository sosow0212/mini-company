from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """도메인 예외의 루트.

    router는 HTTPException을 던지지 않는다. 이 계층만 던지고
    main.py에 등록된 단일 핸들러가 HTTP 상태코드로 번역한다.
    """

    status_code: int = 500
    code: str = "internal_error"
    message: str = "예상치 못한 오류가 발생했습니다."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "요청한 자원을 찾을 수 없습니다."


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )
