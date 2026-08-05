from typing import Annotated

from fastapi import Depends

from src.ledger.repository import LedgerRepository, LedgerRepositoryProtocol
from src.ledger.service import LedgerService
from src.realtime.dependencies import EventBusDep


def get_ledger_repository() -> LedgerRepositoryProtocol:
    return LedgerRepository()


def get_ledger_service(
    repository: Annotated[LedgerRepositoryProtocol, Depends(get_ledger_repository)],
    events: EventBusDep,
) -> LedgerService:
    return LedgerService(repository, events)


LedgerServiceDep = Annotated[LedgerService, Depends(get_ledger_service)]
