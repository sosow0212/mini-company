import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from src.config import get_settings
from src.database import create_mongo_client, init_documents
from src.employees.router import router as employees_router
from src.exceptions import AppError, app_error_handler
from src.health import router as health_router

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    # init_documents는 Mongo에 실제로 접속한다(beanie가 컬렉션 메타를 확인한다).
    # 즉 Mongo가 없으면 앱은 부팅하지 못한다. K8s에서는 startupProbe로 다룬다.
    # readiness의 값은 그대로다 — 런타임 중 DB 장애 시 트래픽에서만 빠지고 재시작되지 않는다.
    app.state.mongo = create_mongo_client(settings)
    await init_documents(app.state.mongo, settings.mongo_db, skip_indexes=True)
    app.state.http = httpx.AsyncClient()
    try:
        yield
    finally:
        # uvicorn이 SIGTERM에 lifespan shutdown을 호출한다.
        await app.state.http.aclose()
        await app.state.mongo.close()


def create_app() -> FastAPI:
    app = FastAPI(title="mini-company", lifespan=lifespan)
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(health_router)
    app.include_router(employees_router, prefix=API_PREFIX)
    return app


app = create_app()
