# mini-company

AI 직원(에이전트)이 수행한 작업을 3D 오피스로 시각화하고, 수집한 데이터를 RAG로 적재해서
나만의 에이전트 오피스를 만들어보세요.

![landing.png](docs/img/landing.png)

- 설계: [`docs/PROJECT_BLUEPRINT.md`](docs/PROJECT_BLUEPRINT.md)
- 에이전트 코딩 규칙: [`AGENTS.md`](AGENTS.md)

## 현재 진행 상황

| Phase | 산출물                                                      | 상태 |
|-------|----------------------------------------------------------|----|
| 0     | 스캐폴딩, 인프라(Mongo replica set / Milvus), 설정, 헬스 프로브        | 완료 |
| 1     | `employees` 도메인 (router→service→repository), 시드, 계약 테스트  | 완료 |
| 2     | `tasks`+`activities` 도메인, 내부 API(`X-Worker-Key`), 워커 하네스 | 완료 |
| 3     | `ledger` 기록·집계·역분개·렌더러, 숫자 무결성 테스트                       | 완료 |
| 4     | `llm` 게이트웨이 (프로파일·단가·비용 자동 기록·폴백), MiniMax/Anthropic 어댑터 | 완료 |
| 5     | `realtime` EventBus + WS 허브 + `/office/snapshot`         | 완료 |
| 6     | 프론트 Three.js 씬 + 아바타 + 말풍선 + 원장 패널                       | 완료 |

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

# 2) 백엔드 + 프론트까지 컨테이너로
make up-all
open http://localhost:5173        # 3D 관제실
```

프론트를 따로 개발할 때는 백엔드가 먼저 떠 있어야 한다(`/api`를 프록시한다):

```bash
cd frontend && npm install
make dev-front                    # http://localhost:5173
make test-front                   # 타입체크 + 단위 테스트
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
GET  /api/v1/office/snapshot                        # 직원 전체 + 원장 요약 (진입 시 1회)
WS   /api/v1/ws/office                              # 이후의 변화분만

# 내부 (워커 전용, X-Worker-Key 헤더 필수)
POST  /internal/v1/tasks                            # 작업 시작 → 직원 WORKING
POST  /internal/v1/tasks/{id}/activities            # 활동 로그 1건 (append-only)
PATCH /internal/v1/tasks/{id}                       # SUCCEEDED/FAILED → 직원 IDLE/ERROR
POST  /internal/v1/ledger/entries                   # 원시 트랜잭션 (append-only)
POST  /internal/v1/ledger/entries/{id}/reversal     # 역분개: 서버가 반대 부호로 기록
POST  /internal/v1/llm/completions                  # LLM 프록시 (모델은 서버가 결정)
```

## LLM 게이트웨이 (§8 — 키·모델·비용의 단일 관문)

모든 LLM 호출이 백엔드를 경유한다. 워커·프론트는 프로바이더 SDK를 갖지 않는다(ADR-007).

- **키는 백엔드 프로세스에만** 있다. K8s로 가도 Secret 마운트 지점이 하나다.
- **모델 선택 권한이 워커에 없다.** 요청에 `model` 필드가 없고, 직원의 `llmProfile`이 정한다.
- **비용을 우회할 수 없다.** 토큰 사용량 → 자체 단가표 → `LedgerEntry(LLM_COST)` 자동 기록.
  프로바이더가 응답에 비용을 담아 보내도 쓰지 않는다(`LlmResult`에 비용 필드가 없다).
- 프로파일 실패 시 `fallback`으로 **1홉만** 재시도하고 Activity에 WARN을 남긴다.
- `LLM_DAILY_COST_LIMIT_KRW` 초과 시 프로바이더를 호출하기 전에 429로 거부한다.

3계층 분리 — 키는 환경변수(Secret), 카탈로그는 코드+`LLM_PROFILES_JSON`(ConfigMap),
직원별 선택은 MongoDB(`Employee.llm_profile`). DB에는 프로파일 **이름만** 저장한다.

부팅 시 카탈로그를 검증한다: 알 수 없는 프로바이더, 없는 fallback, 1홉 초과 폴백,
단가 없는 모델 → **부팅 거부**. 키 누락은 `APP_ENV=local`에서만 경고로 넘어간다
(LLM이 필요 없는 작업 중에 앱이 아예 안 뜨면 개발이 막힌다).

```bash
# 키 없이 전 경로를 확인하려면 base_url을 로컬 목 서버로 돌린다
MINIMAX_API_KEY=dummy MINIMAX_BASE_URL=http://localhost:18080/v1 make dev
```

## 숫자 무결성 (§7 — 이 프로젝트의 심장)

- 화면·요약문의 모든 수치는 `ledger_entries`를 서버가 aggregate한 값이다. 워커는 원시 트랜잭션만 기록한다.
- 금액은 `Decimal`(도메인) ↔ `Decimal128`(Mongo). `$sum`도 Decimal128 위에서 돌아 `0.1 × 3 = 0.3`이다.
- `unit`은 요청에서 받지 않는다 — 카테고리가 결정한다. 같은 카테고리에 KRW와 count가 섞이면 합계가 조용히 무의미해진다.
- 정정은 UPDATE가 아니라 **반대 부호의 새 엔트리**다. 금액을 요청에서 받지 않고 서버가 원본에서 파생한다.
  같은 엔트리의 두 번째 역분개는 409, DB에서도 partial unique 인덱스로 막힌다.
- 요약문의 `{{ledger.revenue.monthly}}`는 서버가 치환한다. 알 수 없는 자리표시자나 남은 `{{`는 예외로 발행을 중단시킨다.

## 실시간 채널 (Phase 5)

스냅샷과 WS가 **짝**이다. 진입 시 `/office/snapshot`으로 현재 상태를 받고, 이후 변화분만
WS로 받는다. **재연결 시에는 반드시 스냅샷을 다시 조회해야 한다** — 이벤트만 이어받으면
끊긴 동안의 변경이 영구히 유실된다.

```jsonc
{ "type": "employee.status_changed", "data": { "employeeId": "…", "status": "WORKING" } }
{ "type": "activity.created",        "data": { "message": "수집 준비 완료", "level": "INFO" } }
{ "type": "ledger.summary_updated",  "data": { "totals": { … }, "net": "-0.3" } }
```

- `type`이 판별자인 discriminated union이라 프론트가 `switch (event.type)` 하나로 분기한다.
- 숫자는 전부 문자열이다. 이벤트의 원장 값도 서버가 aggregate한 결과다(ADR-002).
- 발행은 **상태를 바꾼 service**가 한다. 상태 전이와 발행이 갈라지면 화면이 조용히 멈춘다.
- 브로드캐스트는 `EventBus`를 경유한다(ADR-008). 지금은 `InMemoryEventBus`이고,
  **replica가 2 이상이면 이벤트가 자기 프로세스의 연결에만 가므로** 부팅 시 경고를 남긴다.
  Phase 12에서 `RedisEventBus`로 교체하면 도메인 코드는 그대로다.

## 프론트엔드 (Phase 6)

프레임워크 없이 TypeScript + Three.js + Vite다. UI 상태가 실제로 복잡해지기 전까지는
`store → 구독 → 렌더` 한 방향으로 충분하다.

- **CORS를 열지 않는다.** 개발 서버(vite proxy)와 프로덕션(nginx)이 `/api`를 백엔드로
  프록시해 브라우저 기준 동일 출처를 만든다. 프론트 코드가 환경을 구분하지 않는다.
- **프론트는 계산하지 않는다**(ADR-006). `store`는 서버가 준 값을 갈아끼우기만 하고,
  타입도 금액을 `string`으로 못박아 산술을 막는다. 허용되는 변환은 천 단위 콤마뿐이고
  `Number()`를 거치지 않아 정밀도가 보존된다.
- **상태색의 단일 출처는 CSS다.** `tokens.css`의 hex를 `scene/palette.ts`가 읽어 three의
  Color로 바꾼다 — 3D와 DOM이 같은 초록/빨강을 쓴다.
- 캐릭터는 GLTF 없이 박스+구 프리미티브다(§12). 말풍선은 `CSS2DRenderer` DOM 라벨이라
  한글 줄바꿈이 공짜다. `prefers-reduced-motion`을 존중한다.
- 번들: JS 135 kB gzip, CSS 2.3 kB gzip (App page 예산 300/50 kB 이내).

## 포트

| 포트    | 서비스                                          |
|-------|----------------------------------------------|
| 5173  | frontend (nginx / vite dev)                  |
| 8000  | backend                                      |
| 27018 | mongo (replica set `rs0`) — 27017이 아닌 이유는 아래 |
| 19530 | milvus gRPC                                  |
| 9091  | milvus `/healthz`                            |

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
