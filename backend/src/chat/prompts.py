"""프롬프트 조립. I/O 없는 순수 함수.

숫자 규칙이 이 파일의 본론이다(ADR-002). 자료에 근거하라는 지시만으로는 모델이 숫자를
반올림하거나 합계를 스스로 계산한다. 그래서 **원장 표를 따로 주고, 그 표의 값만 그대로
옮기라고** 명시한다 — 계산은 서버가 이미 했다.
"""

from src.knowledge.domain import SearchHit

SYSTEM_PROMPT = """\
당신은 mini-company의 자료 안내원이다. 회사가 수집한 자료와 원장 요약만으로 답한다.

규칙:
1. [자료]에 있는 내용만 근거로 답한다. 자료에 없는 것은 "자료에 없습니다"라고 말한다.
2. 각 문장 끝에 근거 번호를 [1] 형식으로 붙인다. 여러 개면 [1][2]처럼 이어 쓴다.
3. 숫자는 [원장 요약]에 적힌 값을 **그대로** 옮긴다. 더하거나 빼거나 반올림하지 않는다.
4. [원장 요약]과 [자료]에 없는 숫자는 절대 쓰지 않는다. 모르면 모른다고 답한다.
5. 추측·일반 상식·사전 지식으로 빈칸을 채우지 않는다.
6. 한국어로 간결하게 답한다."""

NOT_FOUND_ANSWER = "자료에 없습니다. 수집된 문서에서 근거를 찾지 못했습니다."


def build_context(hits: list[SearchHit], titles: dict[str, str], ledger_table: str) -> str:
    """검색 결과와 원장 요약을 하나의 사용자 메시지로 만든다.

    번호는 1부터 시작한다 — 응답의 `citations[i].index`와 같은 번호라서, 화면이 [1]을
    실제 문서로 되짚을 수 있다.
    """
    blocks = [
        f"[{index}] (출처: {titles.get(hit.doc_id, '제목 없음')})\n{hit.text}"
        for index, hit in enumerate(hits, start=1)
    ]
    return f"[자료]\n{'\n\n'.join(blocks)}\n\n{ledger_table}"


def build_question(question: str) -> str:
    return f"[질문]\n{question}"
