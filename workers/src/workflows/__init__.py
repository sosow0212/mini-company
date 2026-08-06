"""작업 종류 → 실행 함수.

직원에게 시킬 수 있는 일의 목록이 여기 한 곳에 있다. 새 종류를 추가할 때 에이전트
루프(`src/agent.py`)를 고칠 일이 없어야 한다 — 루프는 "집어서 레지스트리에서 찾아
실행한다"만 안다.

각 워크플로우는 `TaskContext`를 받아 진행 상황을 활동으로 남기고, 마지막에 요약
문장을 반환한다. 시작·마감·실패 처리는 하네스가 이미 보장하므로 여기서 하지 않는다.

**수치를 직접 쓰지 않는다.** 금액이 필요하면 `{{ledger.*}}` 자리표시자를 남기고
서버가 치환한다(ADR-002).
"""

from collections.abc import Awaitable, Callable

from src.runtime.client import BackendApiClient
from src.runtime.harness import TaskContext
from src.workflows import analyze, collect, report

# (client, task, employee_id, title) → 요약 문장
Workflow = Callable[[BackendApiClient, TaskContext, str, str | None], Awaitable[str]]

WORKFLOWS: dict[str, Workflow] = {
    "collect_market_data": collect.run,
    "analyze_knowledge": analyze.run,
    "write_report": report.run,
}


def describe() -> list[dict[str, str]]:
    """UI가 "무엇을 시킬 수 있는지" 보여줄 때 쓰는 목록."""
    return [
        {"kind": kind, "label": _LABELS[kind], "description": _DESCRIPTIONS[kind]}
        for kind in WORKFLOWS
    ]


_LABELS = {
    "collect_market_data": "자료 수집",
    "analyze_knowledge": "자료 분석",
    "write_report": "보고서 작성",
}

_DESCRIPTIONS = {
    "collect_market_data": "외부 소스에서 문서를 가져와 지식 베이스에 적재한다.",
    "analyze_knowledge": "적재된 자료를 검색해 핵심을 정리한다. LLM을 쓴다.",
    "write_report": "근거를 찾아 보고서 문장을 작성한다. 근거가 없으면 쓰지 않는다.",
}
