"""OpenAI 임베딩. httpx로 직접 호출한다(LLM 어댑터와 같은 이유 — SDK 없이 충분하다).

배치로 보낸다. 청크 하나당 왕복을 하면 문서 한 건에 수십 번 네트워크를 타게 된다.
"""

import httpx
from pydantic import SecretStr

from src.knowledge.exceptions import EmbeddingFailed

_MAX_BATCH = 96


class OpenAiEmbeddingProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        dimension: int,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self.dimension = dimension
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def is_configured(self) -> bool:
        return bool(self._api_key.get_secret_value())

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if texts == []:
            return []

        vectors: list[list[float]] = []
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
            headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
        ) as client:
            for start in range(0, len(texts), _MAX_BATCH):
                batch = texts[start : start + _MAX_BATCH]
                vectors.extend(await self._embed_batch(client, batch))
        return vectors

    async def _embed_batch(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        try:
            response = await client.post(
                "/embeddings",
                # dimensions를 명시해 설정된 차원과 응답이 어긋나지 않게 한다.
                json={"model": self._model, "input": batch, "dimensions": self.dimension},
            )
        except httpx.HTTPError as exc:
            # 예외에 요청을 붙이지 않는다(키 노출).
            raise EmbeddingFailed(f"openai 연결 실패: {type(exc).__name__}") from exc

        if response.status_code != httpx.codes.OK:
            raise EmbeddingFailed(f"openai가 {response.status_code}를 반환했다")

        try:
            payload = response.json()
            # 응답 순서를 신뢰하지 않고 index로 정렬한다.
            items = sorted(payload["data"], key=lambda item: int(item["index"]))
            vectors = [[float(value) for value in item["embedding"]] for item in items]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingFailed(f"openai 응답을 해석할 수 없다: {type(exc).__name__}") from exc

        if len(vectors) != len(batch):
            raise EmbeddingFailed("요청한 개수와 벡터 개수가 다르다")
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingFailed(
                    f"차원이 설정과 다르다: 기대 {self.dimension}, 실제 {len(vector)}"
                )
        return vectors
