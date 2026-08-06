"""구조적 로깅. stdout에 JSON 한 줄(§10.1).

`backend/src/logging_setup.py`와 거의 같다. **의도적인 중복이다** — 워커 이미지에 백엔드
코드를 넣지 않으려면 패키지가 독립적이어야 하고, 로깅 포매터 40줄을 위해 공용 패키지를
만들면 두 패키지의 배포가 그 패키지에 묶인다. 워커는 uvicorn을 쓰지 않으므로 그 부분만 없다.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Literal

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
    if isinstance(value, str | int | float | bool | type(None)):
        return value
    return str(value)


def configure_logging(*, level: str, log_format: Literal["json", "console"]) -> None:
    formatter: logging.Formatter = (
        JsonFormatter()
        if log_format == "json"
        else logging.Formatter("%(asctime)s %(levelname)-7s %(name)s :: %(message)s")
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
