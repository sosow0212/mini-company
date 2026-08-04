from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """API 경계 DTO의 공통 베이스.

    Python 내부는 snake_case, 프론트로 나가는 응답만 camelCase로 변환한다.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
