"""LLM 게이트웨이 — 모든 LLM 호출이 지나는 단일 관문.

애그리거트가 아니라 서비스 경계다. 소유하는 것은 프로바이더 키, 프로파일 카탈로그,
단가표뿐이고 영속 상태는 갖지 않는다. 직원 정보는 `employees`가, 비용 기록은
`ledger`가, 폴백 경고는 `tasks`의 Activity가 보관한다.

이 관문을 두는 이유(ADR-007):
  - 키가 한 군데(이 프로세스)에만 존재한다. 워커에 키를 배포하지 않는다.
  - 비용 기록을 우회할 수 없다. 토큰 사용량이 단가표를 거쳐 원장에 자동 기록된다.
  - 모델 선택 권한이 워커에 없다. 요청에 `model`이 없고, 직원의 프로파일이 정한다.

내부 라우터뿐이고 공개 엔드포인트는 없다 — 프론트가 LLM을 직접 부르는 경로를 만들지 않는다.
"""

from fastapi import APIRouter

from src.llm.dependencies import LlmServiceDep
from src.llm.schemas import CompletionRequest, CompletionResponse

internal_router = APIRouter(prefix="/llm", tags=["internal-llm"])


@internal_router.post("/completions")
async def create_completion(
    request: CompletionRequest,
    service: LlmServiceDep,
) -> CompletionResponse:
    return await service.complete(request)
