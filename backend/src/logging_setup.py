"""구조적 로깅. stdout에 JSON 한 줄(§10.1).

파일로 쓰지 않는 이유: 컨테이너에서 파일은 사라지고, K8s 로그 수집기는 stdout만 본다.
한 줄로 쓰는 이유: 여러 줄로 나가면 수집기가 이벤트 하나를 여러 개로 쪼갠다
(스택트레이스가 특히 그렇다 — 그래서 exc_info도 한 필드에 담는다).

로컬에서는 `LOG_FORMAT=console`로 사람이 읽는 형식을 쓸 수 있다. 그 외 환경은 json 고정이
낫지만 강제하지는 않는다 — 디버깅 중에 형식을 바꿀 여지를 남긴다.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Literal

# LogRecord의 기본 속성. 이 목록에 없는 필드만 `extra`로 들어온 것이라 판단한다.
_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

# uvicorn이 자기 핸들러를 심으므로 비워서 루트로 올려보낸다. 안 하면 로그가 두 번 나가고
# 한쪽은 JSON이 아니다.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            # 스택트레이스를 한 필드에 담는다. 여러 줄로 내보내면 수집기가 쪼갠다.
            payload["error"] = self.formatException(record.exc_info)
        payload.update(
            {key: _safe(value) for key, value in record.__dict__.items() if key not in _RESERVED}
        )
        return json.dumps(payload, ensure_ascii=False, default=str)


def _safe(value: object) -> object:
    """JSON으로 나갈 수 있는 형태로 만든다. 실패해도 로깅이 예외를 던지면 안 된다."""
    if isinstance(value, str | int | float | bool | type(None)):
        return value
    return str(value)


def configure_logging(*, level: str, log_format: Literal["json", "console"]) -> None:
    """루트 핸들러를 교체한다. 앱·스크립트·워커가 모두 이 함수를 쓴다."""
    formatter: logging.Formatter = (
        JsonFormatter()
        if log_format == "json"
        else logging.Formatter("%(asctime)s %(levelname)-7s %(name)s :: %(message)s")
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # basicConfig는 핸들러가 이미 있으면 조용히 아무것도 하지 않는다. 명시적으로 교체한다.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
