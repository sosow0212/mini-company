"""백엔드 API 클라이언트.

워커는 오직 이 클라이언트를 통해서만 백엔드와 통신한다(ADR-001).
이 파일에 DB 드라이버(pymongo/pymilvus)나 LLM SDK를 import하면 설계 위반이다.
"""

import httpx
from pydantic import BaseModel, Field, SecretStr

_INTERNAL_PREFIX = "/internal/v1"


class TaskStarted(BaseModel):
    """응답 전체를 복제하지 않고 하네스에 필요한 필드만 받는다. 스키마 소유자는 백엔드."""

    id: str


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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
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

    async def find_employee_id(self, name: str) -> str | None:
        """공개 API로 내 id를 해석한다. 워커는 자기 이름 외의 신원을 모른다."""
        res = await self._http.get("/api/v1/employees")
        res.raise_for_status()
        for employee in res.json():
            if employee["name"] == name:
                return employee["id"]
        return None

    async def start_task(self, *, employee_id: str, kind: str) -> TaskStarted:
        res = await self._http.post(
            f"{_INTERNAL_PREFIX}/tasks",
            json={"employeeId": employee_id, "kind": kind},
        )
        res.raise_for_status()
        return TaskStarted.model_validate(res.json())

    async def add_activity(self, task_id: str, *, level: str, message: str) -> None:
        res = await self._http.post(
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
        res = await self._http.post(f"{_INTERNAL_PREFIX}/llm/completions", json=payload)
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

        res = await self._http.post(f"{_INTERNAL_PREFIX}/knowledge/documents", json=payload)
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
        res = await self._http.patch(
            f"{_INTERNAL_PREFIX}/tasks/{task_id}",
            json={"status": status, "summary": summary, "error": error},
        )
        res.raise_for_status()
