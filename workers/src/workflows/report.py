"""보고서 작성 워크플로우.

분석과 나눈 이유: 산출물의 성격이 다르다. 분석은 중간 산출물(요점 정리)이고
보고서는 **사람이 그대로 읽는 문장**이다. 직무별 프로파일도 그래서 갈린다 —
ANALYST는 `structured`(저가), WRITER는 `writer`(고급)를 쓴다(§8.3).

원장 수치가 필요하면 `{{ledger.*}}` 자리표시자를 남긴다. 워커가 숫자를 타이핑하면
그 값의 출처가 원장이 아니게 되고, 그게 ADR-002가 막으려는 것이다.
"""

import logging

from src.runtime.client import BackendApiClient
from src.runtime.harness import TaskContext

logger = logging.getLogger(__name__)

_DEFAULT_TOPIC = "이번 주 동향"

_SYSTEM = (
    "당신은 회사의 작가다. 주어진 자료만 근거로 보고서를 작성한다. "
    "문단 2개 이내로 간결하게 쓴다. 자료에 없는 사실과 숫자를 만들지 않는다."
)


async def run(
    client: BackendApiClient,
    task: TaskContext,
    employee_id: str,
    title: str | None = None,
) -> str:
    topic = (title or "").strip() or _DEFAULT_TOPIC
    await task.log_info(f"보고서 주제 확인: {topic}")

    await task.log_info("근거 자료를 찾는 중")
    hits = await client.search_knowledge(topic)
    if not hits:
        await task.log_warn("근거가 없어 보고서를 쓰지 않습니다")
        return f"'{topic}' 보고서를 작성하지 못했습니다. 근거 자료가 없습니다."

    await task.log_info("초안 작성 중")
    evidence = "\n\n".join(f"[{index}] {hit.text}" for index, hit in enumerate(hits, start=1))
    completion = await client.complete(
        employee_id=employee_id,
        task_id=task.task_id,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"[자료]\n{evidence}\n\n[주제]\n{topic}"},
        ],
    )
    await task.log_info("보고서 작성 완료")
    logger.info("보고서 워크플로우 종료: profile=%s", completion.profile)
    return completion.content.strip()
