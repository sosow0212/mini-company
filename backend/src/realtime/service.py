"""스냅샷 조립.

자체 저장소가 없다 — 각 도메인 service의 결과를 한 응답으로 묶기만 한다.
프론트가 진입 시 3~4번 왕복하는 대신 1번으로 첫 화면을 그릴 수 있게 하는 것이 목적이다.
"""

from src.employees.service import EmployeeService
from src.ledger.constants import Period
from src.ledger.service import LedgerService
from src.realtime.schemas import OfficeSnapshot


class OfficeService:
    def __init__(self, employees: EmployeeService, ledger: LedgerService) -> None:
        self._employees = employees
        self._ledger = ledger

    async def snapshot(self) -> OfficeSnapshot:
        return OfficeSnapshot(
            employees=await self._employees.list_employees(),
            # 원장 패널의 기본 기간. ledger.summary_updated 이벤트와 같은 기간을 써야
            # 스냅샷 직후 도착한 이벤트가 값을 엉뚱하게 덮지 않는다.
            ledger=await self._ledger.summarize(Period.MONTHLY),
        )
