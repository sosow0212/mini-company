"""스케줄러.

크론 파싱과 겹침 방지 설정을 검증한다. 실제 시간이 흐르기를 기다리지 않는다 —
"11시에 정말 도는가"는 APScheduler의 책임이고, 우리 몫은 트리거를 올바르게 구성하는 것과
잡 실패가 스케줄러를 죽이지 않는 것이다.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src import scheduler as scheduler_module
from src.scheduler import build_scheduler, run_job


def test_cron_is_parsed_into_a_trigger() -> None:
    built = build_scheduler(cron="0 11 * * *", job="collect", timezone="Asia/Seoul")

    trigger = built.get_job("collect").trigger
    assert "hour='11'" in str(trigger)
    assert "minute='0'" in str(trigger)


def test_next_run_uses_the_configured_timezone() -> None:
    """ "오전 11시"는 사람이 사는 시간대의 11시다 — UTC로 두면 8시에 돈다."""
    built = build_scheduler(cron="0 11 * * *", job="collect", timezone="Asia/Seoul")

    trigger = built.get_job("collect").trigger
    fire_at = trigger.get_next_fire_time(
        None, datetime(2026, 8, 6, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    )
    assert fire_at.hour == 11
    assert str(fire_at.tzinfo) == "Asia/Seoul"


def test_job_does_not_overlap_itself() -> None:
    """앞 실행이 아직 돌고 있으면 새로 띄우지 않는다 — 같은 직원에게 두 작업을 시키면
    EmployeeBusy(409)가 난다.
    """
    built = build_scheduler(cron="*/1 * * * *", job="collect", timezone="UTC")

    assert built.get_job("collect").max_instances == 1


def test_missed_runs_are_coalesced() -> None:
    """프로세스가 잠깐 멈췄다 살아나면 놓친 실행을 한 번만 따라잡는다."""
    job = build_scheduler(cron="0 11 * * *", job="collect", timezone="UTC").get_job("collect")

    assert job.coalesce is True
    assert job.misfire_grace_time == 300


def test_invalid_cron_is_rejected_at_build_time() -> None:
    """부팅 시 잡히지 않으면 "11시에 왜 안 돌았지"를 다음 날 알게 된다."""
    with pytest.raises(ValueError):
        build_scheduler(cron="이건 크론이 아니다", job="collect", timezone="UTC")


async def test_run_job_swallows_job_failure() -> None:
    """잡이 예외를 던져도 스케줄러가 죽으면 이후 모든 주기 작업이 멈춘다."""
    calls = 0

    async def failing() -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("잡 폭발")

    original = dict(scheduler_module._JOBS)
    scheduler_module._JOBS["boom"] = failing
    try:
        await run_job("boom")
    finally:
        scheduler_module._JOBS.clear()
        scheduler_module._JOBS.update(original)

    assert calls == 1


async def test_run_job_ignores_unknown_name() -> None:
    """설정 오타로 스케줄러가 죽지 않아야 한다."""
    await run_job("존재하지 않는 잡")
