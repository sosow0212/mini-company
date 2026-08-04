from enum import StrEnum


class LedgerCategory(StrEnum):
    """원장 분류. 화면의 모든 수치는 이 카테고리 합계에서 나온다."""

    REVENUE = "REVENUE"
    COST = "COST"
    LLM_COST = "LLM_COST"
    VIEWS = "VIEWS"
    SUBSCRIBERS = "SUBSCRIBERS"


class Period(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"
    ALL = "all"


# 단위는 카테고리가 결정한다. 요청에서 받지 않는 이유:
# 같은 카테고리에 KRW와 count가 섞이면 합계가 조용히 무의미해진다.
CATEGORY_UNITS: dict[LedgerCategory, str] = {
    LedgerCategory.REVENUE: "KRW",
    LedgerCategory.COST: "KRW",
    LedgerCategory.LLM_COST: "KRW",
    LedgerCategory.VIEWS: "count",
    LedgerCategory.SUBSCRIBERS: "count",
}

# 손익(net)에 들어가는 카테고리와 부호. count 단위는 손익에 더할 수 없으므로 제외한다.
NET_SIGNS: dict[LedgerCategory, int] = {
    LedgerCategory.REVENUE: 1,
    LedgerCategory.COST: -1,
    LedgerCategory.LLM_COST: -1,
}
