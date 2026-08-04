"""인덱스 생성 전용 엔트리포인트. K8s에서는 Job으로 실행한다.

앱 부팅에서 분리한 이유: replica가 여럿이면 모든 Pod가 동시에 인덱스를 만들며 경합하고,
큰 컬렉션에서는 인덱스 빌드 시간이 부팅 지연으로 그대로 드러난다.
"""

import asyncio
import logging

from src.config import get_settings
from src.database import create_mongo_client, init_documents

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    client = create_mongo_client(settings)
    try:
        # init_beanie가 Document.Settings.indexes를 읽어 create_index를 호출한다.
        await init_documents(client, settings.mongo_db, skip_indexes=False)
        logger.info("인덱스 생성 완료: db=%s", settings.mongo_db)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
