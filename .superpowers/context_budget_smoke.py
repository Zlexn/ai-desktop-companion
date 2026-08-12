from app.domain.models import ChatRole
from app.providers.base import LLMMessage
from app.services.chat_service import ChatService


def main() -> None:
    role = LLMMessage(role=ChatRole.SYSTEM, content="role")
    memory = LLMMessage(role=ChatRole.SYSTEM, content="memory")
    oldest = LLMMessage(role=ChatRole.USER, content="oldest")
    newest = LLMMessage(role=ChatRole.ASSISTANT, content="newest")
    current = LLMMessage(role=ChatRole.USER, content="current")
    fitted = ChatService._fit_provider_messages(
        [role, memory, oldest, newest, current],
        max_characters=26,
    )
    assert fitted == [role, memory, newest, current], fitted


if __name__ == "__main__":
    main()
