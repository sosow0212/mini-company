from typing import Annotated

from fastapi import Depends

from src.chat.repository import ConversationRepository, ConversationRepositoryProtocol
from src.chat.service import ChatService
from src.config import Settings, get_settings
from src.knowledge.dependencies import get_knowledge_service
from src.knowledge.service import KnowledgeService
from src.ledger.dependencies import get_ledger_service
from src.ledger.service import LedgerService
from src.llm.dependencies import get_llm_service
from src.llm.service import LlmService


def get_conversation_repository() -> ConversationRepositoryProtocol:
    return ConversationRepository()


def get_chat_service(
    repository: Annotated[ConversationRepositoryProtocol, Depends(get_conversation_repository)],
    knowledge: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    ledger: Annotated[LedgerService, Depends(get_ledger_service)],
    llm: Annotated[LlmService, Depends(get_llm_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatService:
    return ChatService(
        repository,
        knowledge,
        ledger,
        llm,
        profile_name=settings.chat_llm_profile,
        history_limit=settings.chat_history_limit,
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
