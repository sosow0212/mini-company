"""해시 기반 결정론적 임베딩 — **개발·테스트 전용.**

의미를 모른다. 단어를 해시해 고정 차원에 뿌리는 bag-of-words라, 같은 단어를 공유하는
문서끼리만 가까워진다. 동의어·문맥은 전혀 잡지 못한다.

그럼에도 두는 이유: API 키 없이 적재→검색→인용 **파이프라인 전체**를 돌려볼 수 있다.
Phase 4에서 LLM을 목 서버로 검증한 것과 같은 접근이다. 프로덕션에서 이걸 쓰면
검색 품질이 조용히 무의미해지므로, 부팅 시 경고를 남긴다.
"""

import hashlib
import math
import re

_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")


class HashingEmbeddingProvider:
    name = "hashing"

    def __init__(self, *, dimension: int) -> None:
        self.dimension = dimension

    def is_configured(self) -> bool:
        # 키가 필요 없다. 항상 쓸 수 있다는 점이 이 프로바이더의 목적이다.
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            # 부호를 해시에서 뽑아 서로 다른 단어가 무조건 같은 방향으로 쌓이지 않게 한다.
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        return _normalize(vector)


def _normalize(vector: list[float]) -> list[float]:
    """COSINE 메트릭을 쓰므로 단위 벡터로 만든다. 영벡터는 첫 축으로 대체한다
    (Milvus가 영벡터를 거부하고, 빈 청크는 애초에 적재되지 않는다).
    """
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return [1.0, *([0.0] * (len(vector) - 1))]
    return [value / norm for value in vector]
