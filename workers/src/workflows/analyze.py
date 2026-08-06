"""자료 분석 워크플로우.

수집해둔 자료를 검색해 LLM으로 정리한다. 여러 단계를 거치며 활동을 남기는 이유는
로그를 예쁘게 하려는 게 아니라, **3D 씬의 말풍선이 이 활동에서 나오기** 때문이다.
단계를 남기지 않으면 화면에서는 직원이 한참 멈춰 있다가 갑자기 끝난 것처럼 보인다.

근거를 못 찾으면 LLM을 부르지 않는다. 물어보면 그럴듯한 답을 만들어내고, 그건
수집한 자료와 무관한 문장이 보고로 남는다는 뜻이다(§11.2와 같은 규칙).
"""

import logging

from src.runtime.client import BackendApiClient
from src.runtime.harness import TaskContext

logger = logging.getLogger(__name__)

# 지시에 제목이 없을 때 쓰는 기본 질의. 수집 워크플로우가 넣어둔 자료를 겨냥한다.
_DEFAULT_QUERY = "시장 동향"

_SYSTEM = (
    "당신은 회사의 분석가다. 주어진 자료만 근거로 핵심을 3줄 이내로 정리한다. "
    "자료에 없는 내용을 추측하지 않는다. 숫자를 새로 만들지 않는다."
)


async def run(
    client: BackendApiClient,
    task: TaskContext,
    employee_id: str,
    title: str | None = None,
) -> str:
    query = (title or "").strip() or _DEFAULT_QUERY
    await task.log_info(f"자료 검색 시작: {query}")

    hits = await client.search_knowledge(query)
    if not hits:
        # 실패가 아니다. "자료가 없다"는 정당한 결론이고, 그대로 보고한다.
        await task.log_warn("근거를 찾지 못해 분석을 건너뜁니다")
        return f"'{query}'에 대한 자료가 지식 베이스에 없습니다. 먼저 수집이 필요합니다."

    await task.log_info("근거 확보. 정리를 시작합니다")
    evidence = "\n\n".join(f"[{index}] {hit.text}" for index, hit in enumerate(hits, start=1))
    completion = await client.complete(
        employee_id=employee_id,
        task_id=task.task_id,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"[자료]\n{evidence}\n\n[요청]\n{query}에 대해 정리해줘"},
        ],
    )
    await task.log_info("분석 완료")
    logger.info("분석 워크플로우 종료: profile=%s", completion.profile)
    return completion.content.strip()
