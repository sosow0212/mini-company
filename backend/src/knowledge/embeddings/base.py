"""임베딩 프로바이더 경계.

프로바이더를 바꿔도 service는 수정되지 않는다. 다만 **차원이 바뀌면 기존 벡터를 전부
버려야 한다** — 그래서 dimension을 인터페이스에 노출하고 부팅 시 컬렉션과 비교한다(§15-1).
"""

from typing import Protocol


class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def is_configured(self) -> bool: ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """입력 순서와 같은 순서로 벡터를 돌려준다. 실패 시 EmbeddingFailed."""
        ...
