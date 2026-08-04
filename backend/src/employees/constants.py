from enum import StrEnum

# 직원이 참조하는 LLM 프로파일의 기본값. 실제 모델·단가는 llm/profiles.py가 소유한다.
# 여기에 모델명을 두면 3계층 분리(§8.1)가 무너진다.
DEFAULT_LLM_PROFILE = "cheap"


class Role(StrEnum):
    """직무. 블루프린트 §1의 용어를 그대로 쓴다."""

    COLLECTOR = "COLLECTOR"
    WRITER = "WRITER"
    ANALYST = "ANALYST"
    TRADER = "TRADER"
    ENGINEER = "ENGINEER"


class EmployeeStatus(StrEnum):
    """3D 씬의 아바타 색과 1:1 대응한다(블루프린트 §12)."""

    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    WORKING = "WORKING"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


# 직무별 기본 프로파일(§8.3). 원칙: 출력이 사람에게 그대로 노출되는 직무에만 비싼 모델.
# 판단은 코드가 하고 LLM에는 표현만 맡기면 대부분의 직무가 저가 모델로 충분하다.
#
# 블루프린트 표는 ENGINEER에 `coder`(anthropic)를 주지만, 기본 카탈로그에 anthropic
# 프로파일을 두면 ANTHROPIC_API_KEY 없이 부팅 검증이 실패한다. `reasoner`로 두고,
# coder가 필요하면 LLM_PROFILES_JSON과 함께 이 매핑을 바꾼다.
ROLE_LLM_PROFILES: dict[Role, str] = {
    # 수집·파싱은 코드가 한다. LLM은 분류/정제 보조용이라 품질 요구가 낮다.
    Role.COLLECTOR: "structured",
    # 산출물이 JSON(중간 산출물). temperature 0, 최저가로 충분하다.
    Role.ANALYST: "structured",
    # 문장 자체가 최종 산출물. 여기서 아끼면 결과물 품질이 바로 떨어진다.
    Role.WRITER: "writer",
    # 매매 판단은 규칙 기반 코드. LLM은 사유 설명문만 생성한다.
    Role.TRADER: "cheap",
    # 코드 수정은 실패 비용이 가장 크다.
    Role.ENGINEER: "reasoner",
}
