import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import Depends, FastAPI

from src.chat.router import public_router as chat_public_router
from src.config import get_settings
from src.database import create_mongo_client, init_documents
from src.dependencies import require_worker_key
from src.employees.router import router as employees_router
from src.exceptions import AppError, app_error_handler
from src.health import router as health_router
from src.knowledge.router import internal_router as knowledge_internal_router
from src.knowledge.router import public_router as knowledge_public_router
from src.knowledge.settings import build_knowledge_runtime
from src.ledger.router import internal_router as ledger_internal_router
from src.ledger.router import public_router as ledger_public_router
from src.llm.gateway import build_gateway
from src.llm.router import internal_router as llm_internal_router
from src.logging_setup import configure_logging
from src.realtime.factory import attach_realtime
from src.realtime.router import public_router as realtime_public_router
from src.tasks.reaper import run_reaper_loop
from src.tasks.router import internal_router as tasks_internal_router
from src.tasks.router import public_router as tasks_public_router

API_PREFIX = "/api/v1"
INTERNAL_PREFIX = "/internal/v1"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # basicConfig가 아니라 명시적 교체다 — 핸들러가 이미 있으면 basicConfig는 조용히
    # 아무것도 하지 않고, uvicorn이 자기 핸들러를 먼저 심는다(§10.1).
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    # init_documents는 Mongo에 실제로 접속한다(beanie가 컬렉션 메타를 확인한다).
    # 즉 Mongo가 없으면 앱은 부팅하지 못한다. K8s에서는 startupProbe로 다룬다.
    # readiness의 값은 그대로다 — 런타임 중 DB 장애 시 트래픽에서만 빠지고 재시작되지 않는다.
    app.state.mongo = create_mongo_client(settings)
    await init_documents(app.state.mongo, settings.mongo_db, skip_indexes=True)
    app.state.http = httpx.AsyncClient()
    # 카탈로그·단가 검증이 여기서 일어난다. 잘못된 프로파일이면 예외로 부팅이 멈춘다 —
    # 런타임 첫 호출에서 발견되면 이미 늦다(§8.2). 담기는 값은 전부 불변이고
    # 설정에서 재구성 가능하므로 ADR-008에 걸리지 않는다.
    app.state.llm_gateway = build_gateway(settings)
    # service가 publish → 버스 → 이 프로세스의 허브 → WS 연결.
    # 이 조립 지점만 바꾸면 Phase 12에서 RedisEventBus로 교체된다(도메인 코드는 그대로).
    attach_realtime(app, settings)

    # 파서 등록 누락과 임베딩 차원 불일치를 여기서 잡는다. 특히 차원 불일치는
    # 통과시키면 예외 없이 검색 품질만 조용히 망가진다(§15-1).
    app.state.knowledge = build_knowledge_runtime(settings)
    await app.state.knowledge.vector_store.ensure_ready(settings.embedding_dim)

    # 워커가 SIGKILL로 죽으면 작업이 RUNNING에 남아 그 직원이 영구히 EmployeeBusy가 된다.
    # 사람 개입 없이 그 상태가 풀려야 "하루 무인 운영"이 성립한다(Phase 9).
    reaper = (
        asyncio.create_task(run_reaper_loop(settings, app.state.event_bus))
        if settings.reaper_interval_seconds > 0
        else None
    )
    logger.info(
        "부팅 완료",
        extra={"app_env": settings.app_env, "reaper": reaper is not None},
    )
    try:
        yield
    finally:
        # uvicorn이 SIGTERM에 lifespan shutdown을 호출한다. 여기서 하는 일의 순서가 중요하다:
        # 먼저 백그라운드 루프를 세우고(새 작업 생성 중단), 그다음 열린 WS를 닫고,
        # 마지막에 커넥션을 정리한다. 순서를 바꾸면 이미 닫힌 Mongo에 회수 쿼리가 나간다.
        logger.info("종료 시작")
        if reaper is not None:
            await _cancel(reaper)
        await app.state.connection_hub.close_all()
        await app.state.http.aclose()
        await app.state.knowledge.client.close()
        await app.state.mongo.close()
        logger.info("종료 완료")


async def _cancel(task: asyncio.Task[None]) -> None:
    """취소를 기다린다. 기다리지 않으면 이벤트 루프가 닫힌 뒤 태스크가 깨어나
    "Task was destroyed but it is pending" 경고가 남는다.
    """
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def create_app() -> FastAPI:
    app = FastAPI(title="mini-company", lifespan=lifespan)
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(health_router)
    app.include_router(employees_router, prefix=API_PREFIX)
    app.include_router(tasks_public_router, prefix=API_PREFIX)
    app.include_router(ledger_public_router, prefix=API_PREFIX)
    app.include_router(realtime_public_router, prefix=API_PREFIX)
    app.include_router(knowledge_public_router, prefix=API_PREFIX)
    app.include_router(chat_public_router, prefix=API_PREFIX)
    # 내부 라우터는 include 시점에 한 번에 잠근다. 엔드포인트마다 Depends를 붙이면
    # 새 엔드포인트를 추가할 때 반드시 하나 빠뜨린다(블루프린트 §5).
    for internal_router in (
        tasks_internal_router,
        ledger_internal_router,
        llm_internal_router,
        knowledge_internal_router,
    ):
        app.include_router(
            internal_router,
            prefix=INTERNAL_PREFIX,
            dependencies=[Depends(require_worker_key)],
        )
    return app


app = create_app()
