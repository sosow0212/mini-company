"""RAG 챗봇 비즈니스 로직.

흐름(§11.2):
  1. 질문 임베딩 → 벡터 검색
  2. **점수 임계값을 통과한 근거가 없으면 LLM을 부르지 않고** "자료에 없음"으로 끝낸다
  3. 원장 요약을 컨텍스트에 주입(항상)
  4. LLM 호출 — 자료에만 근거, [n] 출처 표기, 숫자는 표에서 그대로 인용
  5. 답변 + citations 저장 및 반환

2번이 이 파일의 핵심이다. 근거가 없을 때 모델에게 물어보면 그럴듯한 답을 만들어낸다.
**출처 없는 답변이 나오지 않는다**는 완료 조건은 검색 단계에서 지켜야 한다.

`citations`는 **검색 결과로 서버가 채운다.** LLM 출력에서 `[1]`을 파싱해 만들면 모델이
표기를 빼먹는 순간 출처 없는 답변이 통과한다.
"""

import logging
from datetime import UTC, datetime

from beanie import PydanticObjectId

from src.chat.domain import Citation, Conversation, Message, MessageRole
from src.chat.exceptions import ConversationNotFound
from src.chat.prompts import NOT_FOUND_ANSWER, SYSTEM_PROMPT, build_context, build_question
from src.chat.repository import ConversationRepositoryProtocol
from src.chat.schemas import AnswerResponse, ConversationResponse
from src.chat.tools import allowed_numbers, render_ledger_table, warn_on_invented_numbers
from src.knowledge.domain import SearchHit
from src.knowledge.service import KnowledgeService
from src.ledger.constants import Period
from src.ledger.service import LedgerService
from src.llm.providers.base import Message as LlmMessage
from src.llm.service import LlmService

logger = logging.getLogger(__name__)

_EXCERPT_LENGTH = 240
_TITLE_LENGTH = 60


class ChatService:
    def __init__(
        self,
        repository: ConversationRepositoryProtocol,
        knowledge: KnowledgeService,
        ledger: LedgerService,
        llm: LlmService,
        *,
        profile_name: str,
        history_limit: int,
    ) -> None:
        self._repository = repository
        self._knowledge = knowledge
        self._ledger = ledger
        self._llm = llm
        self._profile_name = profile_name
        self._history_limit = history_limit

    async def start_conversation(self, title: str | None = None) -> ConversationResponse:
        conversation = await self._repository.save(
            Conversation(
                title=(title or "새 대화").strip()[:_TITLE_LENGTH],
                created_at=datetime.now(UTC),
            )
        )
        return ConversationResponse.from_domain(conversation)

    async def get_conversation(self, conversation_id: PydanticObjectId) -> ConversationResponse:
        conversation = await self._require(conversation_id)
        return ConversationResponse.from_domain(conversation)

    async def list_conversations(self, limit: int) -> list[ConversationResponse]:
        conversations = await self._repository.list_recent(limit=limit)
        return [ConversationResponse.from_domain(item) for item in conversations]

    async def ask(self, conversation_id: PydanticObjectId, question: str) -> AnswerResponse:
        conversation = await self._require(conversation_id)
        now = datetime.now(UTC)
        asked = Message(role=MessageRole.USER, content=question, created_at=now)

        hits = await self._knowledge.search_hits(question)
        if hits == []:
            # 근거가 없으면 모델을 부르지 않는다. 물어보면 그럴듯한 답을 만들어낸다.
            logger.info("근거 없는 질문 — LLM 호출을 생략한다: %s", question[:60])
            answered = Message(
                role=MessageRole.ASSISTANT,
                content=NOT_FOUND_ANSWER,
                created_at=datetime.now(UTC),
                grounded=False,
            )
            await self._append(conversation, asked, answered)
            return AnswerResponse.of(answered, conversation_id=str(conversation_id))

        citations = await self._build_citations(hits)
        summary = await self._ledger.summarize(Period.MONTHLY)
        context = build_context(
            hits,
            {citation.doc_id: citation.title for citation in citations},
            render_ledger_table(summary),
        )

        completion = await self._llm.complete_with_profile(
            self._profile_name,
            [
                LlmMessage(role="system", content=SYSTEM_PROMPT),
                *self._history(conversation),
                LlmMessage(role="user", content=f"{context}\n\n{build_question(question)}"),
            ],
        )
        # 근거 없는 숫자가 섞였는지 확인한다. 하드 차단은 오탐이 많아 경고만 남긴다(§7.3).
        warn_on_invented_numbers(completion.content, allowed_numbers(summary, context))

        answered = Message(
            role=MessageRole.ASSISTANT,
            content=completion.content,
            created_at=datetime.now(UTC),
            citations=citations,
            grounded=True,
        )
        await self._append(conversation, asked, answered)
        return AnswerResponse.of(answered, conversation_id=str(conversation_id))

    async def _require(self, conversation_id: PydanticObjectId) -> Conversation:
        conversation = await self._repository.get(conversation_id)
        if conversation is None:
            raise ConversationNotFound
        return conversation

    async def _build_citations(self, hits: list[SearchHit]) -> tuple[Citation, ...]:
        titles = await self._knowledge.titles_by_doc_id([hit.doc_id for hit in hits])
        return tuple(
            Citation(
                index=index,
                doc_id=hit.doc_id,
                chunk_index=hit.chunk_index,
                title=titles.get(hit.doc_id, "제목 없음"),
                # 인용문은 짧게. 화면이 원문 전체를 보여줄 필요는 없다.
                excerpt=hit.text[:_EXCERPT_LENGTH],
                score=f"{hit.score:.4f}",
            )
            for index, hit in enumerate(hits, start=1)
        )

    def _history(self, conversation: Conversation) -> list[LlmMessage]:
        """직전 대화만 보낸다. 전체를 보내면 토큰이 대화 길이에 비례해 늘어난다."""
        recent = conversation.messages[-self._history_limit :]
        return [LlmMessage(role=message.role.value, content=message.content) for message in recent]

    async def _append(self, conversation: Conversation, *messages: Message) -> None:
        await self._repository.save(
            conversation.model_copy(update={"messages": (*conversation.messages, *messages)})
        )
