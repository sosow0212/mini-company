# mini-company

AI 직원(에이전트)이 수행한 작업을 3D 오피스로 시각화하고, 수집한 데이터를 RAG로 적재해
챗봇으로 질의하는 학습용 시스템.

- 설계: [`docs/PROJECT_BLUEPRINT.md`](docs/PROJECT_BLUEPRINT.md)
- 에이전트 코딩 규칙: [`AGENTS.md`](AGENTS.md)

## 현재 진행 상황

| Phase | 산출물 | 상태 |
|---|---|---|
| 0 | 스캐폴딩, 인프라(Mongo replica set / Milvus), 설정, 헬스 프로브 | 완료 |
| 1 | `employees` 도메인 (router→service→repository), 시드, 계약 테스트 | 완료 |
| 2 | `tasks`+`activities` 도메인, 내부 API(`X-Worker-Key`), 워커 하네스 | 완료 |
| 3 | `ledger` 기록·집계·역분개·렌더러, 숫자 무결성 테스트 | 완료 |

## 실행

```bash
cp .env.example .env
python3 -m venv backend/.venv && backend/.venv/bin/pip install -e 'backend[dev]'
python3 -m venv workers/.venv && workers/.venv/bin/pip install -e 'workers[dev]'

# 1) 인프라만 컨테이너로 (개발 중 권장)
make up
make indexes && make seed
make dev
curl -s localhost:8000/api/v1/employees

# 2) 백엔드까지 컨테이너로
make up-all
curl -s localhost:8000/api/v1/employees
```

더미 워커 1회 실행 (백엔드와 시드가 먼저):

```bash
make worker-demo
curl -s localhost:8000/api/v1/tasks
# 활동 로그 확인
EMPLOYEE_ID=$(curl -s localhost:8000/api/v1/employees | jq -r '.[0].id')
curl -s "localhost:8000/api/v1/employees/${EMPLOYEE_ID}/activities"
```

`make up` 직후 Milvus는 부팅에 1분 가까이 걸린다. `docker compose ps`로 `healthy`를 확인한다.

```bash
make test        # 백엔드 단위 테스트. 인프라 불필요, DB 없이 돈다
make test-int    # 통합/계약 테스트. 인프라 필요
make test-e2e    # e2e (작업 1건 여정). 인프라 필요
make test-worker # 워커 단위 테스트. 인프라 불필요
make lint        # ruff
make indexes     # 인덱스 생성 (K8s에서는 Job)
make seed        # 직원 5명 시드 (멱등)
make worker-demo # 더미 수집 워커 1회 실행
make down        # 정지
make clean       # 볼륨까지 삭제
```

## API

```
GET  /health/live                                   # 의존성 검사 없음
GET  /health/ready                                  # mongo + milvus 검사, 실패 시 503
GET  /api/v1/employees?role=&status=
GET  /api/v1/employees/{id}
GET  /api/v1/employees/{id}/activities?limit=&cursor=   # { items, nextCursor }
GET  /api/v1/tasks?employee_id=&status=
GET  /api/v1/ledger/summary?period=daily|monthly|all    # 서버가 aggregate한 값만

# 내부 (워커 전용, X-Worker-Key 헤더 필수)
POST  /internal/v1/tasks                            # 작업 시작 → 직원 WORKING
POST  /internal/v1/tasks/{id}/activities            # 활동 로그 1건 (append-only)
PATCH /internal/v1/tasks/{id}                       # SUCCEEDED/FAILED → 직원 IDLE/ERROR
POST  /internal/v1/ledger/entries                   # 원시 트랜잭션 (append-only)
POST  /internal/v1/ledger/entries/{id}/reversal     # 역분개: 서버가 반대 부호로 기록
```

## 숫자 무결성 (§7 — 이 프로젝트의 심장)

- 화면·요약문의 모든 수치는 `ledger_entries`를 서버가 aggregate한 값이다. 워커는 원시 트랜잭션만 기록한다.
- 금액은 `Decimal`(도메인) ↔ `Decimal128`(Mongo). `$sum`도 Decimal128 위에서 돌아 `0.1 × 3 = 0.3`이다.
- `unit`은 요청에서 받지 않는다 — 카테고리가 결정한다. 같은 카테고리에 KRW와 count가 섞이면 합계가 조용히 무의미해진다.
- 정정은 UPDATE가 아니라 **반대 부호의 새 엔트리**다. 금액을 요청에서 받지 않고 서버가 원본에서 파생한다.
  같은 엔트리의 두 번째 역분개는 409, DB에서도 partial unique 인덱스로 막힌다.
- 요약문의 `{{ledger.revenue.monthly}}`는 서버가 치환한다. 알 수 없는 자리표시자나 남은 `{{`는 예외로 발행을 중단시킨다.

## 포트

| 포트 | 서비스 |
|---|---|
| 8000 | backend |
| 27018 | mongo (replica set `rs0`) — 27017이 아닌 이유는 아래 |
| 19530 | milvus gRPC |
| 9091 | milvus `/healthz` |

## Mongo 접속 주소가 두 벌인 이유

**포트가 27018인 이유** — 호스트에 로컬 설치된 mongod가 `127.0.0.1:27017`을 점유하고 있으면,
`localhost:27017`로 붙는 프로세스가 compose 컨테이너가 아니라 그 로컬 mongod에 조용히 붙는다.
그 서버는 replica set이 아니라서 Phase 3의 트랜잭션에서야 문제가 드러난다. 주소로 구분되게 비켰다.

**`directConnection=true`가 필요한 이유** — replica set 멤버가 `mongo:27017`로 등록돼 있어서
호스트에서 `?replicaSet=rs0`로 붙으면 드라이버가 컨테이너 이름을 해석하려다 서버 선택에 실패한다.

- 호스트 (`.env`): `mongodb://localhost:27018/?directConnection=true`
- 컨테이너 (compose `environment`): `mongodb://mongo:27017/?replicaSet=rs0`

직결이어도 replica set 멤버이므로 트랜잭션은 그대로 쓸 수 있다.
통합 테스트는 붙은 서버가 replica set인지 확인하고, 아니면 실패한다.

## 레이어

```
router.py       HTTP만. 비즈니스 로직 0줄.
service.py      비즈니스 로직. Beanie 쿼리 금지. 도메인 모델만 다룬다.
repository.py   Beanie 쿼리는 여기서만. Document ↔ 도메인 모델 변환도 여기.
domain.py       순수 도메인 모델(frozen). 지속성 기술을 모른다.
models.py       Beanie Document. 이 파일 밖으로 나가지 않는다.
schemas.py      API DTO. 응답은 camelCase.
```

`domain.py`와 `models.py`를 나눈 이유: beanie 2.x의 `Document.__init__`이 컬렉션 핸들을
요구해서, Document를 도메인 모델로 쓰면 인스턴스를 만드는 것만으로 Mongo 접속이 필요해진다.
그러면 ADR-004가 약속한 "service 테스트에서 DB가 사라진다"가 성립하지 않는다.
매핑 함수 2개를 비용으로 내고 그 보상을 지켰다 — `make test`는 DB 없이 0.2초에 돈다.
