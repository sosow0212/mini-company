"""구조적 로깅. 순수 함수라 mock 0개 — 포매터 출력을 직접 파싱한다.

한 줄 JSON이어야 하는 이유가 검증 대상이다: 여러 줄로 나가면 수집기가 이벤트 하나를
여러 개로 쪼갠다(스택트레이스가 특히 그렇다).
"""

import json
import logging

from src.logging_setup import JsonFormatter, configure_logging


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="작업 회수 %s건",
        args=(3,),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_format_produces_single_line_json() -> None:
    output = JsonFormatter().format(_record())

    assert "\n" not in output
    assert json.loads(output)["message"] == "작업 회수 3건"


def test_format_includes_level_logger_and_timestamp() -> None:
    payload = json.loads(JsonFormatter().format(_record()))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    # ISO 8601 + 타임존. 수집기가 파싱할 수 있어야 한다.
    assert payload["ts"].endswith("+00:00")


def test_format_merges_extra_fields() -> None:
    """구조적 로깅의 핵심 — 값을 메시지 문자열에 녹이지 않고 필드로 남긴다."""
    payload = json.loads(JsonFormatter().format(_record(task_id="abc", count=7)))

    assert payload["task_id"] == "abc"
    assert payload["count"] == 7


def test_format_keeps_stack_trace_in_one_field() -> None:
    try:
        raise ValueError("의도된 오류")
    except ValueError:
        import sys

        record = _record()
        record.exc_info = sys.exc_info()
        output = JsonFormatter().format(record)

    assert "\n" not in output
    payload = json.loads(output)
    assert "ValueError" in payload["error"]
    assert "의도된 오류" in payload["error"]


def test_format_stringifies_unserializable_values() -> None:
    """로깅이 예외를 던지면 그 자체가 장애다. 어떤 값이 와도 한 줄이 나가야 한다."""
    payload = json.loads(JsonFormatter().format(_record(obj=object())))

    assert isinstance(payload["obj"], str)


def test_configure_logging_replaces_existing_handlers() -> None:
    """basicConfig는 핸들러가 있으면 조용히 아무것도 하지 않는다 — uvicorn이 먼저 심는다."""
    root = logging.getLogger()
    root.addHandler(logging.NullHandler())
    before = len(root.handlers)

    configure_logging(level="INFO", log_format="json")

    assert len(root.handlers) == 1
    assert before >= 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_configure_logging_console_format_is_not_json() -> None:
    configure_logging(level="DEBUG", log_format="console")
    root = logging.getLogger()

    assert not isinstance(root.handlers[0].formatter, JsonFormatter)
    assert root.level == logging.DEBUG

    # 다른 테스트에 영향을 주지 않게 되돌린다.
    configure_logging(level="INFO", log_format="json")
