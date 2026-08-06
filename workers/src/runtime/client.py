"""백엔드 API 클라이언트.

워커는 오직 이 클라이언트를 통해서만 백엔드와 통신한다(ADR-001).
이 파일에 DB 드라이버(pymongo/pymilvus)나 LLM SDK를 import하면 설계 위반이다.
"""

import httpx
from pydantic import BaseModel, Field, SecretStr

from src.runtime.retry import with_connection_retry

_INTERNAL_PREFIX = "/internal/v1"

# LLM 호출만 별도 타임아웃을 쓴다. 공용 10초는 "백엔드가 죽었나"를 빨리 알아채기 위한
# 값인데, 생성은 원래 오래 걸린다(로컬 모델이면 분 단위). 전체를 늘리면 진짜 장애를
# 늦게 발견하고, 그대로 두면 정상 생성이 ReadTimeout으로 잘린다.
_LLM_TIMEOUT_SECONDS = 300.0


class TaskStarted(BaseModel):
    """응답 전체를 복제하지 않고 하네스에 필요한 필드만 받는다. 스키마 소유자는 백엔드."""

    id: str


class LlmNotConfigured(Exception):
    """프로바이더 키가 없어 LLM을 부를 수 없다.

    별도 예외로 두는 이유: 이건 버그가 아니라 설정 문제다. 하네스가 이 메시지를 그대로
    작업 실패 사유로 남기고, 화면의 작업 목록에 뜬다.
    """


class ClaimedTask(BaseModel):
    """사람이 지시한 작업. 집어온 시점에 이미 RUNNING이다."""

    id: str
    employee_id: str = Field(alias="employeeId")
    kind: str
    title: str | None = None


class KnowledgeHit(BaseModel):
    doc_id: str = Field(alias="docId")
    text: str
    score: float


class Completion(BaseModel):
    """LLM 프록시 응답.

    `costKrw`를 문자열로 받고 계산에 쓰지 않는다 — 워커는 비용을 다루지 않는다.
    모델명도 서버가 알려주는 값이지 워커가 고르는 값이 아니다(ADR-007).
    """

    content: str
    profile: str
    model: str
    cost_krw: str = Field(alias="costKrw")


class IngestedDocument(BaseModel):
    id: str
    title: str
    chunk_count: int = Field(alias="chunkCount")


class Ingested(BaseModel):
    """적재 결과.

    `skippedDuplicate`는 오류가 아니다 — 워커가 같은 피드를 다시 긁는 것은 정상이고,
    이 플래그로 "새로 적재했는지"를 활동 로그에 남길 수 있다.
    """

    document: IngestedDocument
    skipped_duplicate: bool = Field(alias="skippedDuplicate")


class BackendApiClient:
    def __init__(
        self,
        base_url: str,
        worker_api_key: SecretStr,
        *,
        timeout: float = 10.0,
        max_attempts: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._max_attempts = max_attempts
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Worker-Key": worker_api_key.get_secret_value()},
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> "BackendApiClient":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _send(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        """모든 요청이 여기를 지난다. 연결 실패만 재시도한다(retry.py 참고)."""
        return await with_connection_retry(
            lambda: self._http.request(method, url, **kwargs),
            max_attempts=self._max_attempts,
            label=f"{method} {url}",
        )

    async def find_employee_id(self, name: str) -> str | None:
        """공개 API로 내 id를 해석한다. 워커는 자기 이름 외의 신원을 모른다."""
        res = await self._send("GET", "/api/v1/employees")
        res.raise_for_status()
        for employee in res.json():
            if employee["name"] == name:
                return employee["id"]
        return None

    async def start_task(
        self, *, employee_id: str, kind: str, title: str | None = None
    ) -> TaskStarted:
        res = await self._send(
            "POST",
            f"{_INTERNAL_PREFIX}/tasks",
            json={"employeeId": employee_id, "kind": kind, "title": title},
        )
        res.raise_for_status()
        return TaskStarted.model_validate(res.json())

    async def claim_task(self) -> ClaimedTask | None:
        """대기열에서 하나를 집어온다. 없으면 None(204).

        204는 오류가 아니다 — "지금 시킨 일이 없다"는 대부분의 순간에 참이다.
        """
        res = await self._send("POST", f"{_INTERNAL_PREFIX}/tasks/claim")
        res.raise_for_status()
        if res.status_code == httpx.codes.NO_CONTENT:
            return None
        return ClaimedTask.model_validate(res.json())

    async def search_knowledge(self, query: str, *, top_k: int = 5) -> list[KnowledgeHit]:
        """수집해둔 자료에서 근거를 찾는다. 임계값 미달은 서버가 걸러 보낸다."""
        res = await self._send(
            "GET", "/api/v1/knowledge/search", params={"q": query, "topK": top_k}
        )
        res.raise_for_status()
        return [KnowledgeHit.model_validate(item) for item in res.json()["items"]]

    async def add_activity(self, task_id: str, *, level: str, message: str) -> None:
        res = await self._send(
            "POST",
            f"{_INTERNAL_PREFIX}/tasks/{task_id}/activities",
            json={"level": level, "message": message},
        )
        res.raise_for_status()

    async def complete(
        self,
        *,
        employee_id: str,
        messages: list[dict[str, str]],
        task_id: str | None = None,
    ) -> Completion:
        """LLM 프록시 호출. 워커는 프로바이더를 직접 부르지 않는다(ADR-007).

        `model`을 보내지 않는다 — 어떤 모델을 쓸지는 서버가 직원의 프로파일로 정한다.
        """
        payload: dict[str, object] = {"employeeId": employee_id, "messages": messages}
        if task_id is not None:
            payload["taskId"] = task_id
        res = await self._send(
            "POST",
            f"{_INTERNAL_PREFIX}/llm/completions",
            json=payload,
            timeout=_LLM_TIMEOUT_SECONDS,
        )
        if res.status_code == httpx.codes.SERVICE_UNAVAILABLE:
            # 스택 트레이스를 작업 실패 사유로 남기면 화면에 URL과 상태코드만 뜬다.
            # 원인과 해결책을 한 문장으로 바꿔야 사용자가 다음에 뭘 할지 안다.
            raise LlmNotConfigured(
                "LLM이 설정되지 않아 이 작업을 할 수 없습니다. "
                ".env에 OLLAMA_ENABLED=true(로컬 모델)를 넣거나 API 키를 설정하세요."
            )
        res.raise_for_status()
        return Completion.model_validate(res.json())

    async def ingest_document(
        self,
        *,
        employee_id: str,
        source_type: str,
        content_type: str,
        text: str | None = None,
        base64_content: str | None = None,
        source_url: str | None = None,
        title: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Ingested:
        """수집 문서를 백엔드에 넘긴다.

        **파싱하지 않는다.** 텍스트 추출과 메타태그 해석은 백엔드가 한다(ADR-001) —
        규칙이 워커마다 갈라지면 같은 HTML에서 다른 제목이 나온다. 워커의 일은
        "어디서 무슨 포맷으로 가져왔는지"를 알려주는 것까지다.
        """
        payload: dict[str, object] = {
            "employeeId": employee_id,
            "sourceType": source_type,
            "contentType": content_type,
            "collectedBy": employee_id,
        }
        for key, value in (
            ("text", text),
            ("base64Content", base64_content),
            ("sourceUrl", source_url),
            ("title", title),
            ("taskId", task_id),
        ):
            if value is not None:
                payload[key] = value
        if metadata:
            payload["metadata"] = metadata

        res = await self._send("POST", f"{_INTERNAL_PREFIX}/knowledge/documents", json=payload)
        res.raise_for_status()
        return Ingested.model_validate(res.json())

    async def finish_task(
        self,
        task_id: str,
        *,
        status: str,
        summary: str | None = None,
        error: str | None = None,
    ) -> None:
        res = await self._send(
            "PATCH",
            f"{_INTERNAL_PREFIX}/tasks/{task_id}",
            json={"status": status, "summary": summary, "error": error},
        )
        res.raise_for_status()
