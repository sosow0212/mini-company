from beanie import init_beanie
from pymongo import AsyncMongoClient

from src.config import Settings
from src.employees.models import EmployeeDocument
from src.tasks.models import ActivityDocument, TaskDocument

_SERVER_SELECTION_TIMEOUT_MS = 3000

# Phase가 진행되며 여기에 Document를 추가한다. 등록을 빠뜨리면 해당 컬렉션 쿼리가
# 런타임에 CollectionWasNotInitialized로 터진다.
DOCUMENT_MODELS = [EmployeeDocument, TaskDocument, ActivityDocument]


def create_mongo_client(settings: Settings) -> AsyncMongoClient:
    """클라이언트 생성 자체는 연결하지 않는다(lazy). 실제 접속은 첫 명령에서 일어난다."""
    return AsyncMongoClient(
        settings.mongo_uri,
        tz_aware=True,
        serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS,
    )


async def init_documents(
    client: AsyncMongoClient,
    db_name: str,
    *,
    skip_indexes: bool,
) -> None:
    """Beanie Document를 컬렉션에 바인딩한다.

    skip_indexes=True가 기본 운용이다. 인덱스 생성은 앱 부팅이 아니라
    별도 Job(`make indexes`)이 담당한다 — replica가 여럿이면 부팅마다 경합한다.
    """
    await init_beanie(
        database=client[db_name],
        document_models=DOCUMENT_MODELS,
        skip_indexes=skip_indexes,
    )
