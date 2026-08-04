import asyncio
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request, Response, status
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

_PROBE_TIMEOUT_SECONDS = 2.0


@router.get("/live")
async def live() -> dict[str, str]:
    """liveness. 외부 의존성을 검사하지 않는다.

    실패하면 K8s가 Pod를 재시작한다. 여기에 DB 검사를 넣으면
    DB가 잠깐 느려질 때 전체 Pod 재시작 폭풍으로 증폭된다.
    """
    return {"status": "ok"}


@router.get("/ready")
async def ready(
        request: Request,
        response: Response,
        settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    """readiness. 실패하면 트래픽에서만 제외되고 재시작되지 않는다."""
    mongo_ok, milvus_ok = await asyncio.gather(
        _ping_mongo(request.app.state.mongo),
        _ping_milvus(request.app.state.http, settings.milvus_health_url),
    )
    is_ready = mongo_ok and milvus_ok

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": is_ready, "checks": {"mongo": mongo_ok, "milvus": milvus_ok}}


async def _ping_mongo(client: AsyncMongoClient) -> bool:
    try:
        await client.admin.command("ping")
    except PyMongoError:
        logger.warning("readiness: mongo ping 실패", exc_info=True)
        return False
    return True


async def _ping_milvus(http: httpx.AsyncClient, url: str) -> bool:
    try:
        res = await http.get(url, timeout=_PROBE_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        logger.warning("readiness: milvus healthz 요청 실패", exc_info=True)
        return False
    if res.status_code != status.HTTP_200_OK:
        logger.warning("readiness: milvus healthz가 %s를 반환", res.status_code)
        return False
    return True
