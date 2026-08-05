"""대화(Conversation) 애그리거트 — 사용자 질문과 근거가 달린 답변.

소유하는 것은 대화 이력과 각 답변의 인용 목록뿐이다. 자료 원문은 `knowledge`가,
수치는 `ledger`가, LLM 호출 비용은 `llm` 게이트웨이가 원장에 기록한다. 여기서
숫자를 계산하거나 자료를 저장하지 않는다.

공개 라우터만 있다 — 사람이 쓰는 기능이라 워커 키를 요구하지 않는다. 대신 **쓰기가
공개된 유일한 엔드포인트**이므로, 인터넷에 노출할 때는 운영자 인증이 필요하다
(현재 인증 개념은 워커 키뿐이고, 그 설계는 아직 없다).
"""

from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Query, status

from src.chat.dependencies import ChatServiceDep
from src.chat.schemas import (
    AnswerResponse,
    AskRequest,
    ConversationResponse,
    StartConversationRequest,
)

public_router = APIRouter(prefix="/chat", tags=["chat"])

_DEFAULT_LIST_LIMIT = 20
_MAX_LIST_LIMIT = 100


@public_router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def start_conversation(
    request: StartConversationRequest,
    service: ChatServiceDep,
) -> ConversationResponse:
    return await service.start_conversation(request.title)


@public_router.get("/conversations")
async def list_conversations(
    service: ChatServiceDep,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIST_LIMIT)] = _DEFAULT_LIST_LIMIT,
) -> list[ConversationResponse]:
    return await service.list_conversations(limit)


@public_router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: PydanticObjectId,
    service: ChatServiceDep,
) -> ConversationResponse:
    return await service.get_conversation(conversation_id)


@public_router.post("/conversations/{conversation_id}/messages")
async def ask(
    conversation_id: PydanticObjectId,
    request: AskRequest,
    service: ChatServiceDep,
) -> AnswerResponse:
    """질문 1건 → 근거가 달린 답변 1건.

    근거를 찾지 못하면 LLM을 부르지 않고 `grounded=false`로 답한다 — 출처 없는 답변이
    나오지 않는다는 규칙은 검색 단계에서 지켜진다.
    """
    return await service.ask(conversation_id, request.content)
