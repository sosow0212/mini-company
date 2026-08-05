from src.exceptions import NotFoundError


class ConversationNotFound(NotFoundError):
    code = "conversation_not_found"
    message = "해당 대화를 찾을 수 없습니다."
