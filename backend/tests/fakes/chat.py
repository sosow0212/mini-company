from beanie import PydanticObjectId

from src.chat.domain import Conversation


class InMemoryConversationRepository:
    def __init__(self, conversations: list[Conversation] | None = None) -> None:
        self._by_id: dict[PydanticObjectId, Conversation] = {}
        for conversation in conversations or []:
            self._by_id[_require_id(conversation)] = conversation

    async def get(self, conversation_id: PydanticObjectId) -> Conversation | None:
        return self._by_id.get(conversation_id)

    async def save(self, conversation: Conversation) -> Conversation:
        stored = (
            conversation
            if conversation.id is not None
            else conversation.model_copy(update={"id": PydanticObjectId()})
        )
        self._by_id[_require_id(stored)] = stored
        return stored

    async def list_recent(self, *, limit: int) -> list[Conversation]:
        ordered = sorted(self._by_id.values(), key=lambda item: item.created_at, reverse=True)
        return ordered[:limit]


def _require_id(conversation: Conversation) -> PydanticObjectId:
    if conversation.id is None:
        raise ValueError("저장된 대화에는 id가 있어야 한다")
    return conversation.id
