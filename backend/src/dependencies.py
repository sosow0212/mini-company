"""전역 DI. 특정 도메인에 속하지 않는 횡단 관심사(인증)만 둔다."""

import secrets
from typing import Annotated

from fastapi import Depends, Header

from src.config import Settings, get_settings
from src.exceptions import WorkerKeyUnauthorized


async def require_worker_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_worker_key: Annotated[str | None, Header()] = None,
) -> None:
    """내부 API의 유일한 잠금. main.py에서 /internal/v1 라우터 전체에 한 번에 건다.

    비교는 compare_digest로 — == 비교는 타이밍으로 키를 유추할 수 있다.
    """
    expected = settings.worker_api_key.get_secret_value().encode("utf-8")
    provided = (x_worker_key or "").encode("utf-8")
    if not secrets.compare_digest(provided, expected):
        raise WorkerKeyUnauthorized
