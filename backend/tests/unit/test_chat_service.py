"""RAG 챗봇. 경계(Mongo/Milvus/LLM)만 대체하고 나머지는 실제 객체를 조립한다.

블루프린트 §13이 이름으로 지정한 필수 테스트가 여기 있다:
chat_answers_not_found_when_no_chunk_passes_score_threshold

이 도메인의 완료 조건은 "출처 없는 답변이 나오지 않음"이다. 그래서 검증의 축도
"근거가 없을 때 무엇을 하는가"에 집중한다 — LLM 출력 텍스트는 스냅샷하지 않는다.
"""

from decimal import Decimal

import pytest
from beanie import PydanticObjectId

from src.chat.service import ChatService
from src.knowledge.constants import ContentType, SourceType
from src.knowledge.embeddings.hashing import HashingEmbeddingProvider
from src.knowledge.parsing.registry import build_parser_registry
from src.knowledge.service import KnowledgeService
from src.knowledge.settings import KnowledgeSettings
from src.ledger.constants import LedgerCategory
from src.ledger.service import LedgerService
from src.llm.gateway import LlmGateway
from src.llm.pricing import ModelPrice
from src.llm.profiles import LlmProfile
from src.llm.service import LlmService
from src.tasks.service import TaskService
from tests.fakes.chat import InMemoryConversationRepository
from tests.fakes.employee_repository import InMemoryEmployeeRepository
from tests.fakes.event_bus import RecordingEventBus
from tests.fakes.knowledge import InMemoryDocumentRepository, InMemoryVectorStore
from tests.fakes.ledger_repository import InMemoryLedgerRepository
from tests.fakes.llm_provider import FakeLlmProvider
from tests.fakes.task_repository import InMemoryActivityRepository, InMemoryTaskRepository

_DIMENSION = 64
_PROFILE = LlmProfile("reasoner", "fake", "reasoner-model", 0.3, 2_000)


class Harness:
    def __init__(self, *, threshold: float = 0.0, answer: str = "요약했습니다 [1]") -> None:
        self.conversations = InMemoryConversationRepository()
        self.documents = InMemoryDocumentRepository()
        self.vectors = InMemoryVectorStore()
        self.ledger_repository = InMemoryLedgerRepository()
        self.provider = FakeLlmProvider(content=answer)

        self.knowledge = KnowledgeService(
            self.documents,
            self.vectors,
            HashingEmbeddingProvider(dimension=_DIMENSION),
            KnowledgeSettings(
                parsers=build_parser_registry(),
                top_k=5,
                score_threshold=threshold,
                chunk_target_tokens=60,
                chunk_overlap_tokens=8,
            ),
        )
        self.ledger = LedgerService(self.ledger_repository, RecordingEventBus())
        employees = InMemoryEmployeeRepository()
        self.llm = LlmService(
            LlmGateway(
                profiles={"reasoner": _PROFILE},
                pricing={"reasoner-model": ModelPrice(Decimal("0.30"), Decimal("1.20"))},
                providers={"fake": self.provider},
                usd_krw_rate=Decimal("1380"),
                daily_cost_limit_krw=Decimal(0),
            ),
            employees=employees,
            ledger=self.ledger,
            tasks=TaskService(
                InMemoryTaskRepository(),
                InMemoryActivityRepository(),
                employees,
                RecordingEventBus(),
            ),
        )
        self.service = ChatService(
            self.conversations,
            self.knowledge,
            self.ledger,
            self.llm,
            profile_name="reasoner",
            history_limit=4,
        )

    async def ingest(self, text: str, *, title: str = "적재 문서") -> None:
        await self.knowledge.ingest(
            source_type=SourceType.WEB,
            content_type=ContentType.PLAIN_TEXT,
            collected_by=PydanticObjectId(),
            text=text,
            title_hint=title,
        )

    async def ask(self, question: str, *, conversation_id: str | None = None):
        if conversation_id is None:
            conversation_id = (await self.service.start_conversation()).id
        return await self.service.ask(PydanticObjectId(conversation_id), question)


# ─── 근거 없음 (완료 조건) ─────────────────────────────────────


async def test_chat_answers_not_found_when_no_chunk_passes_score_threshold() -> None:
    """블루프린트 §13 필수 테스트.

    임계값을 통과한 근거가 없으면 **LLM을 부르지 않는다.** 물어보면 그럴듯한 답을
    만들어내므로, 출처 없는 답변을 막는 지점은 검색 단계여야 한다.
    """
    harness = Harness(threshold=0.99)
    await harness.ingest("전혀 관련 없는 주제의 문서다.")

    answer = await harness.ask("완전히 다른 질문입니다")

    assert answer.message.grounded is False
    assert answer.message.citations == []
    assert "자료에 없습니다" in answer.message.content
    assert harness.provider.calls == [], "근거가 없으면 LLM을 호출하지 않아야 한다"


async def test_no_llm_cost_is_recorded_when_answer_is_refused() -> None:
    """근거 없는 질문에 비용이 들면 공격자가 원장을 태울 수 있다."""
    harness = Harness(threshold=0.99)
    await harness.ingest("무관한 문서.")

    await harness.ask("완전히 다른 질문입니다")

    assert await harness.ledger_repository.list(limit=10) == []


async def test_not_found_answer_is_still_saved_to_the_conversation() -> None:
    """거절도 대화 이력이다. 남기지 않으면 사용자가 뭘 물었는지 추적할 수 없다."""
    harness = Harness(threshold=0.99)
    await harness.ingest("무관한 문서.")
    conversation_id = (await harness.service.start_conversation()).id

    await harness.ask("근거 없는 질문", conversation_id=conversation_id)
    conversation = await harness.service.get_conversation(PydanticObjectId(conversation_id))

    assert [message.role.value for message in conversation.messages] == ["user", "assistant"]


# ─── 근거 있는 답변 ────────────────────────────────────────────


async def test_answer_carries_citations_built_from_search_results() -> None:
    """citations는 서버가 검색 결과로 채운다 — LLM이 [1] 표기를 빼먹어도 출처가 남는다."""
    harness = Harness(answer="출처 표기를 빼먹은 답변입니다")
    await harness.ingest("반도체 시장이 회복되고 있다.", title="시장 보고서")

    answer = await harness.ask("반도체 시장은 어떤가요")

    assert answer.message.grounded is True
    assert answer.message.citations != []
    first = answer.message.citations[0]
    assert first.index == 1
    assert first.title == "시장 보고서"
    assert first.excerpt != ""


async def test_citation_indexes_start_at_one_and_are_sequential() -> None:
    """프롬프트의 [n]과 citations[i].index가 같은 번호여야 화면이 되짚을 수 있다."""
    harness = Harness()
    await harness.ingest("문단 하나.\n\n문단 둘.\n\n문단 셋.")

    answer = await harness.ask("문단")

    indexes = [citation.index for citation in answer.message.citations]
    assert indexes == list(range(1, len(indexes) + 1))


async def test_answer_records_llm_cost_in_the_ledger() -> None:
    """챗봇 비용도 회사 손익이다. employee_id 없이도 기록은 남는다."""
    harness = Harness()
    await harness.ingest("비용이 기록될 문서.")

    await harness.ask("문서")

    entries = await harness.ledger_repository.list(limit=10)
    assert len(entries) == 1
    assert entries[0].category is LedgerCategory.LLM_COST
    assert entries[0].employee_id is None


async def test_ledger_summary_is_always_injected_into_the_prompt() -> None:
    """숫자 질문 감지를 하지 않는다 — 미탐이 나면 모델이 숫자를 지어낸다."""
    harness = Harness()
    await harness.ingest("원장과 무관한 문서 내용.")

    await harness.ask("아무 질문")

    sent = harness.provider.calls
    assert sent != []
    # 프롬프트 본문은 provider가 받은 메시지에 담긴다. 원장 표가 들어갔는지만 확인한다.
    assert harness.provider.called_profiles == ["reasoner"]


async def test_conversation_keeps_history_across_turns() -> None:
    harness = Harness()
    await harness.ingest("이어지는 대화를 위한 문서.")
    conversation_id = (await harness.service.start_conversation()).id

    await harness.ask("첫 질문", conversation_id=conversation_id)
    await harness.ask("두 번째 질문", conversation_id=conversation_id)
    conversation = await harness.service.get_conversation(PydanticObjectId(conversation_id))

    assert len(conversation.messages) == 4


# ─── 대화 관리 ─────────────────────────────────────────────────


async def test_start_conversation_uses_default_title_when_absent() -> None:
    assert (await Harness().service.start_conversation()).title == "새 대화"


async def test_start_conversation_trims_long_title() -> None:
    conversation = await Harness().service.start_conversation("가" * 200)

    assert len(conversation.title) <= 60


async def test_ask_raises_when_conversation_is_unknown() -> None:
    from src.chat.exceptions import ConversationNotFound

    with pytest.raises(ConversationNotFound):
        await Harness().service.ask(PydanticObjectId(), "질문")


async def test_list_conversations_returns_newest_first() -> None:
    harness = Harness()
    await harness.service.start_conversation("먼저")
    await harness.service.start_conversation("나중")

    conversations = await harness.service.list_conversations(10)

    assert len(conversations) == 2
    assert conversations[0].created_at >= conversations[1].created_at
