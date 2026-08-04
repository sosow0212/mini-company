"""핵심 여정: 워커가 작업 1건을 시작해 완료하기까지, 공개 API에 어떻게 보이는가.

Phase 2 완료 조건("더미 워커가 작업 1건 완주")의 자동화된 형태다.
실제 Mongo + 실제 DI 그래프 위에서 HTTP로만 검증한다.
"""

from datetime import UTC, datetime

from src.employees.constants import Role
from src.employees.domain import DeskPosition, Employee
from src.employees.repository import EmployeeRepository


async def test_worker_journey_from_task_start_to_finish_is_visible_in_public_api(
    client,
) -> None:
    # 준비: 직원이 입사해 있다 (시드 역할)
    employee = await EmployeeRepository().save(
        Employee(
            name="수집가 노아",
            role=Role.COLLECTOR,
            desk=DeskPosition(x=0.0, y=0.0, z=0.0),
            hired_at=datetime.now(UTC),
        )
    )

    # 1. 워커가 작업을 시작한다
    started = await client.post(
        "/internal/v1/tasks",
        json={"employeeId": str(employee.id), "kind": "collect_market_data"},
    )
    assert started.status_code == 201
    task = started.json()
    assert task["status"] == "RUNNING"

    # 2. 공개 API에서 직원이 일하는 모습이 보인다
    view = await client.get(f"/api/v1/employees/{employee.id}")
    assert view.json()["status"] == "WORKING"
    assert view.json()["currentTaskId"] == task["id"]

    # 3. 작업 중 활동 로그를 남긴다
    messages = ["수집 준비 완료", "외부 소스 접속 확인", "수집 완료"]
    for message in messages:
        res = await client.post(
            f"/internal/v1/tasks/{task['id']}/activities", json={"message": message}
        )
        assert res.status_code == 201

    # 4. 작업을 완료한다
    finished = await client.patch(
        f"/internal/v1/tasks/{task['id']}",
        json={"status": "SUCCEEDED", "summary": "더미 수집 작업 완료"},
    )
    assert finished.status_code == 200
    assert finished.json()["status"] == "SUCCEEDED"
    assert finished.json()["finishedAt"] is not None

    # 5. 직원은 자리로 돌아온다
    view = await client.get(f"/api/v1/employees/{employee.id}")
    assert view.json()["status"] == "IDLE"
    assert view.json()["currentTaskId"] is None

    # 6. 활동 로그는 최신순으로 공개된다
    activities = await client.get(f"/api/v1/employees/{employee.id}/activities")
    assert [item["message"] for item in activities.json()["items"]] == [
        "수집 완료",
        "외부 소스 접속 확인",
        "수집 준비 완료",
    ]

    # 7. 작업 목록에서도 완료 상태가 조회된다
    tasks = await client.get("/api/v1/tasks", params={"employee_id": str(employee.id)})
    assert tasks.json()[0]["status"] == "SUCCEEDED"
