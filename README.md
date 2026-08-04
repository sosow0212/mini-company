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

## 실행

```bash
cp .env.example .env
python3 -m venv backend/.venv && backend/.venv/bin/pip install -e 'backend[dev]'

# 1) 인프라만 컨테이너로 (개발 중 권장)
make up
make indexes && make seed
make dev
curl -s localhost:8000/api/v1/employees

# 2) 백엔드까지 컨테이너로
make up-all
curl -s localhost:8000/api/v1/employees
```

`make up` 직후 Milvus는 부팅에 1분 가까이 걸린다. `docker compose ps`로 `healthy`를 확인한다.

```bash
make test      # 단위 테스트. 인프라 불필요, DB 없이 돈다
make test-int  # 통합/계약 테스트. 인프라 필요
make lint      # ruff
make indexes   # 인덱스 생성 (K8s에서는 Job)
make seed      # 직원 5명 시드 (멱등)
make down      # 정지
make clean     # 볼륨까지 삭제
```

## API

```
GET /health/live                            # 의존성 검사 없음
GET /health/ready                           # mongo + milvus 검사, 실패 시 503
GET /api/v1/employees?role=&status=
GET /api/v1/employees/{id}
```

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
