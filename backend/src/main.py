import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from pymongo import AsyncMongoClient

from src.config import get_settings
from src.health import router as health_router

_MONGO_SERVER_SELECTION_TIMEOUT_MS = 3000


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    # 두 클라이언트 모두 생성 시점에 연결하지 않는다(lazy).
    # 의존성이 아직 안 떴을 때 앱이 죽지 않고 /health/ready가 503을 내는 것이 목표다.
    app.state.mongo = AsyncMongoClient(
        settings.mongo_uri,
        tz_aware=True,
        serverSelectionTimeoutMS=_MONGO_SERVER_SELECTION_TIMEOUT_MS,
    )
    app.state.http = httpx.AsyncClient()
    try:
        yield
    finally:
        # uvicorn이 SIGTERM에 lifespan shutdown을 호출한다.
        await app.state.http.aclose()
        await app.state.mongo.close()


def create_app() -> FastAPI:
    app = FastAPI(title="mini-company", lifespan=lifespan)
    app.include_router(health_router)
    return app


app = create_app()
