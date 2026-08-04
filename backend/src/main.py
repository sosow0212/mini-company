import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI

from src.config import get_settings
from src.database import create_mongo_client, init_documents
from src.dependencies import require_worker_key
from src.employees.router import router as employees_router
from src.exceptions import AppError, app_error_handler
from src.health import router as health_router
from src.ledger.router import internal_router as ledger_internal_router
from src.ledger.router import public_router as ledger_public_router
from src.tasks.router import internal_router as tasks_internal_router
from src.tasks.router import public_router as tasks_public_router

API_PREFIX = "/api/v1"
INTERNAL_PREFIX = "/internal/v1"


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
    app.include_router(tasks_public_router, prefix=API_PREFIX)
    app.include_router(ledger_public_router, prefix=API_PREFIX)
    # 내부 라우터는 include 시점에 한 번에 잠근다. 엔드포인트마다 Depends를 붙이면
    # 새 엔드포인트를 추가할 때 반드시 하나 빠뜨린다(블루프린트 §5).
    for internal_router in (tasks_internal_router, ledger_internal_router):
        app.include_router(
            internal_router,
            prefix=INTERNAL_PREFIX,
            dependencies=[Depends(require_worker_key)],
        )
    return app


app = create_app()
