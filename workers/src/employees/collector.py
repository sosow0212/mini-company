"""수집 직원.

Phase 7의 완료 조건은 "문서 수집 → 벡터 검색 동작"이다. 실제 외부 소스(RSS/웹 크롤링)를
붙이는 대신 **여러 포맷을 백엔드에 넘기는 경로**를 검증한다 — 이 워커가 하는 일은
"어디서 무슨 포맷으로 가져왔는지 알려주기"까지이고, 파싱·메타추출·청킹·임베딩은
전부 백엔드가 한다(ADR-001).

새 소스를 붙일 때 이 파일이 커지지 않는다. `_SOURCES`에 항목 하나를 추가하면 되고,
새 **포맷**이 필요하면 백엔드 `knowledge/parsing/`에 파서를 등록한다.

실행: cd workers && .venv/bin/python -m src.employees.collector
"""

import asyncio
import base64
import logging
from dataclasses import dataclass, field

import httpx

from src.runtime.client import BackendApiClient
from src.runtime.config import get_settings
from src.runtime.harness import run_task

logger = logging.getLogger(__name__)

_TASK_KIND = "collect_market_data"


@dataclass(frozen=True)
class Source:
    """수집 대상 1건.

    `metadata`는 워커가 **이미 아는** 값이다(피드 이름 등). 백엔드에서 파서 추출값 위에
    덮이므로, 문서 안에 없는 맥락 정보를 여기로 넘긴다.
    """

    label: str
    source_type: str
    content_type: str
    text: str | None = None
    data: bytes | None = None
    source_url: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


_HTML_ARTICLE = """<!doctype html><html lang="ko"><head>
<title>폴백 제목</title>
<meta property="og:title" content="메모리 반도체 수요 회복">
<meta name="description" content="데이터센터 투자가 늘며 수요가 개선됐다">
<meta name="author" content="박기자">
<meta property="article:published_time" content="2026-08-04T00:00:00Z">
<meta name="keywords" content="반도체, 메모리, 데이터센터">
<meta property="og:site_name" content="테크뉴스">
</head><body>
<nav>사이트 메뉴</nav>
<h1>메모리 반도체 수요 회복</h1>
<p>메모리 반도체 수요가 회복되고 있다. 데이터센터 투자 확대가 주된 배경이다.</p>
<p>파운드리 가동률도 개선되는 추세이며, 후공정 업체의 수주도 늘었다.</p>
<footer>저작권 표시</footer></body></html>"""

_MARKDOWN_NOTE = """---
title: 주간 시장 메모
author: 리아
date: 2026-08-03
tags: 시장, 메모
---
# 주간 시장 메모

이번 주 관찰한 내용을 정리한다. 데이터센터 관련 수요가 특히 강했다.

- 메모리 가격이 반등했다.
- 후공정 업체 수주가 늘었다.
"""

_PLAIN_BRIEF = """오늘 확인한 내용을 짧게 남긴다.

데이터센터 투자가 늘어나면서 메모리 반도체 주문이 증가했다.
후공정 업체들도 가동률이 올라갔다고 전해진다."""

_SOURCES: tuple[Source, ...] = (
    Source(
        label="웹 기사(HTML)",
        source_type="WEB",
        content_type="HTML",
        text=_HTML_ARTICLE,
        source_url="https://example.test/semiconductor-demand",
        metadata={"feed": "tech-rss"},
    ),
    Source(
        label="작업 메모(Markdown)",
        source_type="FILE",
        content_type="MARKDOWN",
        text=_MARKDOWN_NOTE,
    ),
    Source(
        label="짧은 브리프(줄글)",
        source_type="API",
        content_type="PLAIN_TEXT",
        text=_PLAIN_BRIEF,
        # 줄글은 문서 안에 제목이 없다. 아는 값을 hint로 넘긴다.
        metadata={"title": "데이터센터 수요 브리프"},
    ),
)


async def _collect(client: BackendApiClient, task, *, employee_id: str) -> tuple[int, int]:
    ingested = 0
    skipped = 0
    for source in _SOURCES:
        try:
            result = await client.ingest_document(
                employee_id=employee_id,
                source_type=source.source_type,
                content_type=source.content_type,
                text=source.text,
                base64_content=(
                    base64.b64encode(source.data).decode() if source.data is not None else None
                ),
                source_url=source.source_url,
                task_id=task.task_id,
                metadata=source.metadata,
            )
        except httpx.HTTPStatusError as exc:
            # 한 문서가 실패해도 다음 문서로 진행한다(§11.1). 실패는 ERROR로 남긴다.
            await task.log_error(f"{source.label} 적재 실패 (응답 {exc.response.status_code})")
            continue

        if result.skipped_duplicate:
            skipped += 1
            await task.log_info(f"{source.label} 이미 적재된 문서 건너뜀")
        else:
            ingested += 1
            # 수치를 문장에 쓰지 않는다 — 활동 메시지에 숫자를 넣지 않는 규칙(§7.3).
            await task.log_info(f"{source.label} 적재 완료: {result.document.title}")
    return ingested, skipped


async def run() -> int:
    settings = get_settings()
    async with BackendApiClient(
        base_url=settings.backend_base_url, worker_api_key=settings.worker_api_key
    ) as client:
        employee_id = await client.find_employee_id(settings.employee_name)
        if employee_id is None:
            logger.error(
                "직원을 찾을 수 없다: %s (make seed가 먼저 필요하다)", settings.employee_name
            )
            return 1

        async with run_task(client, employee_id=employee_id, kind=_TASK_KIND) as task:
            await task.log_info("수집 준비 완료")
            ingested, skipped = await _collect(client, task, employee_id=employee_id)
            await task.log_info("수집 완료")
            task.set_summary("수집 작업을 마쳤습니다.")

    logger.info("작업 완주: %s (신규 %d건, 중복 %d건)", settings.employee_name, ingested, skipped)
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
