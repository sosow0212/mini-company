# mini-company — AI 직원 관제실 설계 블루프린트

학습용 프로젝트. FastAPI(백엔드) + Three.js(프론트) + MongoDB + Milvus로,
AI 직원(에이전트)들이 실제로 수행한 작업을 3D 오피스에 시각화하고,
수집한 데이터를 RAG로 적재해 챗봇으로 질의하는 시스템.

인프라는 로컬 `docker-compose`로 시작해 이후 Kubernetes 배포까지 실습하는 것을 전제로 설계한다.
따라서 처음부터 12-Factor 원칙(설정은 환경변수, 프로세스는 무상태, 로그는 stdout)을 지킨다.
LLM은 MiniMax를 기본 프로바이더로 쓰되, 프로바이더 교체가 가능한 어댑터 구조로 둔다.

---

## 1. 도메인 언어 정의 (Ubiquitous Language)

용어를 먼저 고정한다. 이후 모든 코드/테이블/API가 이 단어만 쓴다.

| 용어 | 코드명 | 정의 |
|---|---|---|
| 직원 | `Employee` | AI 에이전트 1명. 3D 씬의 캐릭터 1개와 1:1 대응 |
| 직무 | `Role` | 직원의 역할. `COLLECTOR`, `WRITER`, `ANALYST`, `TRADER`, `ENGINEER` |
| 작업 | `Task` | 직원이 수행하는 1회 실행 단위 (예: "오늘 시장 데이터 수집") |
| 활동 로그 | `Activity` | 작업 중 발생한 append-only 이벤트. **말풍선의 원천** |
| 원장 | `LedgerEntry` | 금액/수치의 원시 트랜잭션. **화면 숫자의 유일한 원천** |
| 문서 | `Document` | 수집 직원이 가져온 원문 1건 (메타데이터는 Mongo) |
| 청크 | `Chunk` | 문서를 쪼갠 조각 + 임베딩 (벡터는 Milvus) |
| 워커 | `Worker` | 직원의 실제 실행 프로세스. 백엔드와 별도 프로세스 |
| LLM 프로파일 | `LlmProfile` | 프로바이더+모델+파라미터 묶음에 붙인 이름. 직원은 이 이름만 참조 |

`Agent`라는 단어는 쓰지 않는다 — `Employee`로 통일. 혼용이 가장 흔한 설계 부패 원인.

---

## 2. 핵심 아키텍처 결정 (ADR 요약)

### ADR-001. 워커는 DB에 직접 쓰지 않는다
워커는 오직 백엔드 내부 API(`X-Worker-Key` 인증)만 호출한다.

- 이유: 검증·상태전이·원장 규칙을 **한 곳(service 레이어)** 에만 둘 수 있다.
  워커가 DB를 직접 만지면 규칙이 워커 수만큼 복제되고, 반드시 갈라진다.
- 대가: 네트워크 홉 1회 추가. 학습 프로젝트 규모에선 무의미한 비용.

### ADR-002. 숫자는 LLM이 타이핑하지 않는다
화면·보고서에 등장하는 모든 수치는 `ledger_entries`를 **서버가 aggregate**해서 만든다.

- 워커/LLM은 `LedgerEntry`(원시 트랜잭션)만 기록할 수 있다.
- 요약문을 생성할 때 LLM은 `{{ledger.revenue.monthly}}` 같은 플레이스홀더만 쓰고,
  서버가 렌더 시점에 실제 값으로 치환한다.
- 챗봇도 동일. 숫자 질문은 LLM이 계산하지 않고 `ledger_summary` 툴 호출 결과만 인용한다.

### ADR-003. `Activity`와 `LedgerEntry`는 append-only
정정은 UPDATE가 아니라 **반대 부호의 새 엔트리**로 남긴다(회계의 역분개).
과거 화면을 그대로 재현할 수 있어야 하고, 이게 감사 가능성의 전부다.

### ADR-004. Repository 레이어를 명시적으로 둔다 (학습 목적)
`router → service → repository → models(Beanie)` 4계층으로 간다.

- 이유: 학습 목적이 우선. 레이어드 아키텍처에서 "지속성 관심사를 어디까지 밀어내는가"를
  몸으로 익히는 게 이 프로젝트의 목표 중 하나다.
- 규칙: **`service.py`에 Beanie 쿼리 API(`find`, `insert`, `aggregate`)가 등장하면 안 된다.**
  이 한 줄이 레이어를 지탱한다. 이게 무너지면 repository는 장식이 된다.
- Repository는 Beanie Document를 반환하고, service가 이를 조합해 `schemas.py`의 DTO로 만든다.
- 테스트 이득: `InMemoryEmployeeRepository` 같은 fake를 만들 수 있어, service 단위 테스트가
  DB 없이 밀리초 단위로 돌아간다. 이건 mock이 아니라 경계 대체이므로 classist 원칙에 부합한다.
- 대가: 단순 CRUD에서 위임만 하는 메서드가 생긴다. 학습 비용으로 감수한다.

### ADR-007. LLM 호출은 백엔드 프록시를 경유한다
워커는 LLM 프로바이더를 직접 호출하지 않고 `POST /internal/v1/llm/completions`를 호출한다.

- 이유 1 — **키가 한 군데에만 존재한다.** 워커가 직접 호출하면 API 키가 백엔드와 워커
  양쪽 환경에 배포되고, K8s로 가면 Secret 마운트 지점이 프로세스 수만큼 늘어난다.
- 이유 2 — **비용 기록을 우회할 수 없다.** 프록시가 토큰 사용량을 받아 단가표로 비용을
  계산하고 `LedgerEntry(category=LLM_COST)`를 자동 기록한다. 워커 구현자가 깜빡할 여지가 없다.
- 이유 3 — **모델 선택 권한이 워커에 없다.** 워커는 `employee_id`만 보내고, 어떤 모델을 쓸지는
  서버가 직원의 `llm_profile`로 결정한다. 모델 정책이 중앙에서 관리된다.
- 대가: 스트리밍이 필요해지면 SSE 패스스루를 추가해야 한다. Phase 8 이후 과제.

### ADR-008. 무상태 + 이벤트 버스 추상화 (K8s 대비)
백엔드는 프로세스 메모리에 **복구 불가능한 상태를 두지 않는다.**

- WebSocket 브로드캐스트 허브는 `EventBus` 인터페이스 뒤에 둔다.
  - 로컬/단일 replica: `InMemoryEventBus`
  - K8s 다중 replica: `RedisEventBus` (Pub/Sub)
- 이걸 미리 추상화하지 않으면 replica를 2로 올리는 순간 "어떤 사용자는 이벤트를 못 받는"
  디버깅 최악의 버그가 생긴다. K8s 실습을 예정한 시점에서 이 결정은 나중이 아니라 지금이다.
- 인메모리 캐시는 허용하되, 없어도 정상 동작해야 한다(캐시는 최적화, 진실은 DB).

### ADR-005. Milvus 벡터는 Mongo 문서와 `doc_id`로만 연결
Milvus에는 검색에 필요한 최소 필드만 넣는다(`doc_id`, `chunk_index`, `text`, `embedding`).
원문·수집 메타·직원 정보는 Mongo에. 벡터 스토어를 진실의 원천으로 삼으면
재인덱싱할 때마다 데이터가 소실된다.

### ADR-006. 프론트는 계산하지 않는다
프론트엔드에 `+`, `*`, `reduce((a,b)=>a+b)` 로 만든 수치가 들어가면 안 된다.
백엔드가 계산해서 내려준 값을 **문자열로 렌더링만** 한다.
(예외: 3D 좌표 보간/애니메이션 — 이건 표현이지 데이터가 아님)

---

## 3. 디렉토리 구조

```
mini-company/                          # ← 현재 디렉토리명 mini-compnay 오타 (수정 권장)
├── README.md
├── AGENTS.md                           # 에이전트 코딩 규칙 (별도 파일)
├── docker-compose.yml                  # 인프라 + 앱 (프로파일로 구분)
├── docker-compose.override.yml         # 로컬 개발용 볼륨 마운트/핫리로드
├── .env.example
├── .env                                # git 추적 제외
├── Makefile                            # up / down / test / lint / seed / k8s-*
│
├── docs/
│   ├── PROJECT_BLUEPRINT.md            # 이 문서
│   └── adr/
│       ├── 001-workers-call-api-only.md
│       ├── 004-repository-layer.md
│       ├── 007-llm-proxy.md
│       └── 008-stateless-event-bus.md
│
├── deploy/
│   ├── docker/
│   │   ├── backend.Dockerfile          # 멀티스테이지, non-root
│   │   ├── worker.Dockerfile
│   │   └── frontend.Dockerfile         # 빌드 → nginx 정적 서빙
│   └── k8s/
│       ├── base/
│       │   ├── namespace.yaml
│       │   ├── configmap.yaml          # 비밀 아닌 설정 (프로파일 카탈로그, 단가표)
│       │   ├── secret.example.yaml     # 실제 Secret은 커밋 금지
│       │   ├── backend-deployment.yaml
│       │   ├── backend-service.yaml
│       │   ├── worker-cronjob.yaml     # 수집/발행 스케줄 작업
│       │   ├── frontend-deployment.yaml
│       │   ├── redis-deployment.yaml   # EventBus (replica ≥ 2일 때 필수)
│       │   ├── ingress.yaml
│       │   └── kustomization.yaml
│       └── overlays/
│           ├── local/                  # kind / minikube (replica 1, NodePort)
│           └── prod/                   # replica 2+, HPA, resource limits
│
├── backend/
│   ├── pyproject.toml
│   ├── src/
│   │   ├── main.py                     # FastAPI 앱 팩토리 + lifespan
│   │   ├── config.py                   # 전역 Settings (pydantic-settings)
│   │   ├── constants.py                # 전역 Enum/상수
│   │   ├── exceptions.py               # 예외 계층 루트 + 핸들러
│   │   ├── database.py                 # Mongo(Beanie) init, Milvus 커넥션
│   │   ├── dependencies.py             # 전역 DI (worker key, pagination)
│   │   ├── health.py                   # /health/live, /health/ready
│   │   ├── pagination.py
│   │   │
│   │   ├── llm/                        # LLM 게이트웨이 (공용 모듈)
│   │   │   ├── router.py               # /internal/v1/llm/completions
│   │   │   ├── schemas.py              # LlmRequest / LlmResponse / Usage
│   │   │   ├── profiles.py             # 프로파일 카탈로그 + 부팅 시 검증
│   │   │   ├── pricing.py              # 토큰 단가표 → 비용 계산 (코드가 계산)
│   │   │   ├── service.py              # 프로파일 해석 → 호출 → 사용량/비용 기록
│   │   │   ├── exceptions.py
│   │   │   └── providers/
│   │   │       ├── base.py             # Protocol: LlmProvider
│   │   │       ├── minimax.py          # 기본 프로바이더
│   │   │       ├── anthropic.py
│   │   │       └── registry.py         # 이름 → 프로바이더 인스턴스
│   │   │
│   │   ├── employees/                  # 직원 관리
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── models.py
│   │   │   ├── repository.py           # Beanie 쿼리는 여기서만
│   │   │   ├── service.py
│   │   │   ├── dependencies.py
│   │   │   ├── constants.py
│   │   │   └── exceptions.py
│   │   │
│   │   ├── tasks/                      # 작업 + 활동 로그
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── models.py
│   │   │   ├── repository.py           # TaskRepository, ActivityRepository
│   │   │   ├── service.py
│   │   │   ├── state_machine.py        # 상태 전이 규칙 (순수 함수)
│   │   │   ├── constants.py
│   │   │   └── exceptions.py
│   │   │
│   │   ├── ledger/                     # 원장 (숫자 무결성)
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── models.py
│   │   │   ├── repository.py           # aggregate 파이프라인 실행
│   │   │   ├── service.py              # 집계 결과 조립
│   │   │   ├── renderer.py             # 플레이스홀더 치환
│   │   │   ├── constants.py
│   │   │   └── exceptions.py
│   │   │
│   │   ├── knowledge/                  # RAG 적재/검색
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── models.py               # SourceDocument (Mongo)
│   │   │   ├── repository.py           # Mongo 문서 접근
│   │   │   ├── vector_store.py         # Milvus 어댑터 (벡터 쪽 repository)
│   │   │   ├── service.py              # 수집→청킹→임베딩→upsert
│   │   │   ├── chunking.py             # 순수 함수
│   │   │   ├── embeddings.py           # 임베딩 프로바이더 (경계)
│   │   │   ├── constants.py
│   │   │   └── exceptions.py
│   │   │
│   │   ├── chat/                       # RAG 챗봇
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── models.py               # Conversation, Message
│   │   │   ├── repository.py
│   │   │   ├── service.py              # retrieve → prompt → answer
│   │   │   ├── prompts.py
│   │   │   ├── tools.py                # ledger_summary 툴
│   │   │   └── exceptions.py
│   │   │
│   │   └── realtime/                   # WebSocket
│   │       ├── router.py
│   │       ├── hub.py                  # 연결 관리
│   │       ├── bus.py                  # EventBus Protocol + InMemory/Redis 구현
│   │       └── schemas.py              # 프론트로 나가는 이벤트 페이로드
│   │
│   └── tests/
│       ├── conftest.py
│       ├── fakes/                      # InMemory*Repository, FakeLlmProvider
│       ├── unit/                       # 순수 로직 + service(fake repo)
│       ├── integration/                # 실제 Mongo/Milvus 사용
│       └── e2e/                        # 핵심 여정 (워커 작업 1건 → 화면 상태)
│
├── workers/                            # 직원 실행 프로세스
│   ├── pyproject.toml
│   ├── src/
│   │   ├── runtime/
│   │   │   ├── client.py               # 백엔드 내부 API 클라이언트 (LLM 프록시 포함)
│   │   │   ├── harness.py              # 작업 시작/활동기록/종료 컨텍스트매니저
│   │   │   └── config.py
│   │   ├── employees/
│   │   │   ├── collector.py            # 데이터 수집 직원
│   │   │   ├── writer.py
│   │   │   └── analyst.py
│   │   └── scheduler.py                # 로컬용 APScheduler (K8s에선 CronJob으로 대체)
│   └── tests/
│
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── index.html
    └── src/
        ├── main.ts
        ├── api/
        │   ├── client.ts               # fetch 래퍼
        │   ├── types.ts                # 백엔드 스키마와 1:1 (수동 or 자동생성)
        │   └── socket.ts               # WS 재연결 포함
        ├── scene/
        │   ├── OfficeScene.ts          # 씬/카메라/렌더러/라이트
        │   ├── OfficeLayout.ts         # 책상 좌표 정의
        │   ├── EmployeeAvatar.ts       # 캐릭터 1명 (메시 + 상태색 + 이동)
        │   ├── Picking.ts              # Raycaster 클릭 판정
        │   └── loop.ts                 # requestAnimationFrame
        ├── state/
        │   └── officeStore.ts          # 서버 스냅샷 보관 (계산 금지)
        └── ui/
            ├── SpeechBubble.ts         # CSS2DRenderer 라벨
            ├── EmployeePanel.ts        # 클릭 시 상세 + 활동 로그
            ├── LedgerPanel.ts          # 서버 계산 숫자만 렌더
            └── ChatPanel.ts            # RAG 챗봇
```

---

## 4. 데이터 모델

### 4.1 MongoDB

```python
# employees/models.py
class Employee(Document):
    name: str
    role: Role                          # Enum
    status: EmployeeStatus = EmployeeStatus.OFFLINE
    desk: DeskPosition                  # x, y, z (임베디드)
    llm_profile: str = "cheap"          # 프로파일 '이름'만 저장. 모델명/키는 저장 금지
    current_task_id: PydanticObjectId | None = None
    hired_at: datetime
    last_seen_at: datetime | None = None

    class Settings:
        name = "employees"
        indexes = ["role", "status"]
```

```python
# tasks/models.py
class Task(Document):
    employee_id: PydanticObjectId
    kind: str                           # "collect_market_data" 등
    status: TaskStatus                  # QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED
    summary: str | None = None          # 플레이스홀더 포함 가능
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

    class Settings:
        name = "tasks"
        indexes = [[("employee_id", 1), ("created_at", -1)]]


class Activity(Document):              # append-only
    employee_id: PydanticObjectId
    task_id: PydanticObjectId | None
    level: ActivityLevel                # INFO/WARN/ERROR
    message: str                        # 말풍선에 그대로 노출 (숫자 금지)
    occurred_at: datetime

    class Settings:
        name = "activities"
        indexes = [[("employee_id", 1), ("occurred_at", -1)]]
```

```python
# ledger/models.py
class LedgerEntry(Document):           # append-only, 절대 수정/삭제 금지
    employee_id: PydanticObjectId | None
    task_id: PydanticObjectId | None
    category: LedgerCategory            # REVENUE/COST/LLM_COST/VIEWS/SUBSCRIBERS/...
    amount: Decimal128                  # float 금지
    unit: str                           # "KRW", "count"
    occurred_at: datetime
    memo: str | None = None
    reverses_id: PydanticObjectId | None = None   # 역분개 대상

    class Settings:
        name = "ledger_entries"
        indexes = [[("category", 1), ("occurred_at", -1)]]
```

> 금액은 반드시 `Decimal128`. float로 원화를 더하면 학습 프로젝트에서도 오차가 난다.

```python
# knowledge/models.py
class Document_(Document):              # 이름 충돌 주의: 클래스명은 SourceDocument 권장
    title: str
    source_url: str | None
    source_type: SourceType             # RSS/WEB/API/FILE
    raw_text: str
    collected_by: PydanticObjectId      # employee_id
    collected_at: datetime
    content_hash: str                   # 중복 수집 차단 (unique index)
    chunk_count: int = 0
    indexed_at: datetime | None = None
```

### 4.2 Milvus 컬렉션 `knowledge_chunks`

| 필드 | 타입 | 비고 |
|---|---|---|
| `pk` | INT64 | auto_id |
| `doc_id` | VARCHAR(24) | Mongo `_id` 문자열 |
| `chunk_index` | INT64 | |
| `text` | VARCHAR(4000) | 원문 조각 (답변 인용용) |
| `source_type` | VARCHAR(16) | 필터 조건 |
| `embedding` | FLOAT_VECTOR | dim은 모델 의존 (config로 관리) |

- metric: `COSINE`, index: `HNSW` (M=16, efConstruction=200)
- 삭제는 `doc_id` 기준 `delete(expr=f'doc_id == "{doc_id}"')` 후 재삽입 (문서 단위 멱등 재인덱싱)

---

## 5. API 설계

### 공개 (read-only, 인증 없음)

```
GET  /api/v1/office/snapshot            # 프론트 최초 진입 1회. 직원 전체 + 원장 요약
GET  /api/v1/employees                  # ?role=&status=
GET  /api/v1/employees/{id}
GET  /api/v1/employees/{id}/activities  # ?limit=20 (커서 페이지네이션)
GET  /api/v1/tasks                      # ?employee_id=&status=
GET  /api/v1/ledger/summary             # ?period=daily|monthly|all
WS   /api/v1/ws/office                  # 실시간 이벤트 스트림
POST /api/v1/chat/conversations
POST /api/v1/chat/conversations/{id}/messages
```

### 내부 (워커 전용, `X-Worker-Key` 필수)

```
POST  /internal/v1/tasks                        # 작업 시작 (직원 status→WORKING)
POST  /internal/v1/tasks/{id}/activities        # 활동 로그 1건
PATCH /internal/v1/tasks/{id}                   # 완료/실패 전이
POST  /internal/v1/ledger/entries               # 원시 트랜잭션 기록
POST  /internal/v1/knowledge/documents          # 수집 문서 적재 (청킹+임베딩 트리거)
POST  /internal/v1/llm/completions              # LLM 프록시 (모델은 서버가 결정)
```

LLM 프록시 요청/응답:

```jsonc
// 요청 — 워커는 employee_id만 보낸다. model 필드가 없는 것이 핵심.
{
  "employeeId": "665f...",
  "taskId": "665f...",
  "messages": [{ "role": "user", "content": "..." }],
  "responseFormat": "text"            // 또는 "json"
}

// 응답
{
  "content": "...",
  "profile": "writer",
  "provider": "minimax",
  "model": "MiniMax-M2.7",
  "usage": { "inputTokens": 1820, "outputTokens": 640 },
  "costKrw": "3.21"                    // 서버가 단가표로 계산, 문자열
}
```

라우터는 두 `APIRouter`로 완전히 분리하고, 내부 라우터는 `include_router(..., dependencies=[Depends(require_worker_key)])`로 한 번에 잠근다. 개별 엔드포인트에 인증을 붙이면 반드시 하나 빠뜨린다.

### WebSocket 이벤트 페이로드

```jsonc
// 서버 → 클라이언트, discriminated union
{ "type": "employee.status_changed", "data": { "employeeId": "...", "status": "WORKING" } }
{ "type": "activity.created",        "data": { "employeeId": "...", "message": "시장 데이터 42건 수집" } }
{ "type": "ledger.summary_updated",  "data": { "revenueMonthly": "82860000", "net": "-1240000" } }
```

- 숫자는 **문자열로 전송**한다 (Decimal → JS number 변환 시 정밀도 손실 방지).
- 프론트는 이 문자열을 그대로 표시한다. 포맷팅(콤마)만 허용.

---

## 6. 레이어 규칙

```
router.py       HTTP만. 요청 파싱 → service 호출 → 응답 스키마 변환. 비즈니스 로직 0줄.
service.py      비즈니스 로직. 트랜잭션 경계. 도메인 예외를 던진다. Beanie 쿼리 금지.
repository.py   지속성만. Beanie 쿼리는 여기서만 등장. 비즈니스 판단 금지.
models.py       Beanie Document. 지속성 표현.
schemas.py      Pydantic 요청/응답 DTO. Document를 API로 그대로 노출하지 않는다.
*.py (순수)     state_machine, chunking, renderer, pricing — I/O 없는 순수 함수.
```

### Repository 작성 규칙

```python
# employees/repository.py
class EmployeeRepository:
    async def get(self, employee_id: PydanticObjectId) -> Employee | None:
        return await Employee.get(employee_id)

    async def list_by_status(self, status: EmployeeStatus) -> list[Employee]:
        return await Employee.find(Employee.status == status).to_list()

    async def save(self, employee: Employee) -> Employee:
        return await employee.save()
```

- 반환 타입은 도메인 모델 또는 원시값. `dict`를 반환하지 않는다(타입 안전성 소실).
- **"없으면 예외"를 repository가 판단하지 않는다.** `None`을 반환하고, 그게 오류인지는
  service가 결정한다. 조회 실패가 정상 흐름인 경우도 있기 때문이다.
- 페이지네이션 파라미터는 받되, 정책(기본 20, 최대 100)은 service/dependency가 정한다.
- DI로 주입한다: `def get_employee_repository() -> EmployeeRepository: return EmployeeRepository()`
  → `service = EmployeeService(repo=Depends(get_employee_repository))`.
  테스트에서 `app.dependency_overrides`로 fake로 교체한다.

### 코드 스타일 고정

- 전부 `async def`. 동기 블로킹 호출(requests, pymongo)은 금지, 불가피하면 `run_in_threadpool`.
- 타입 힌트 100%. `Any` 사용 시 주석으로 이유 명시.
- 도메인 예외는 `exceptions.py`에서 `AppError`를 상속하고, `main.py`의 단일 핸들러가
  HTTP 상태코드로 번역한다. router에서 `HTTPException`을 직접 던지지 않는다.

```python
# exceptions.py (전역)
class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    message: str = "예상치 못한 오류가 발생했습니다."

class NotFoundError(AppError):
    status_code = 404
    code = "not_found"

# employees/exceptions.py
class EmployeeNotFound(NotFoundError):
    message = "해당 직원을 찾을 수 없습니다."
```

### API 경계 네이밍
Python 내부는 `snake_case`, 프론트로 나가는 응답만 `camelCase`로 변환한다.

```python
# schemas.py 공통 베이스
class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
```

---

## 7. 숫자 무결성 파이프라인 (이 프로젝트의 심장)

### 7.1 기록
워커는 계산하지 않는다. 발생한 사실만 남긴다.

```python
await client.post_ledger_entry(
    category="REVENUE", amount="82860000", unit="KRW",
    occurred_at=now, memo="애드센스 정산",
)
```

### 7.2 집계 (서버 전용)

```python
# ledger/service.py
async def summarize(period: Period) -> LedgerSummary:
    pipeline = [
        {"$match": {"occurred_at": {"$gte": period.start, "$lt": period.end}}},
        {"$group": {"_id": "$category", "total": {"$sum": "$amount"}}},
    ]
    rows = await LedgerEntry.aggregate(pipeline).to_list()
    ...
```

### 7.3 요약문 렌더링
LLM 출력 예시:

```
이번 달 매출은 {{ledger.revenue.monthly}}원이고, 순손익은 {{ledger.net.monthly}}원입니다.
```

`ledger/renderer.py`가 치환하며, **알 수 없는 플레이스홀더나 치환되지 않은 `{{`가 남아 있으면
예외를 던져 발행을 중단**한다. 조용히 통과시키면 규칙이 없는 것과 같다.

추가 방어선: `Activity.message`와 LLM 요약 원문에 대해 `\d{3,}` 패턴을 검사해
경고 로그를 남긴다(하드 차단은 오탐이 많아 경고로 시작).

---

## 8. LLM 모델·키 관리

### 8.1 3계층 분리 원칙

이 설계의 핵심은 아래 세 가지를 **절대 같은 곳에 두지 않는 것**이다.

| 무엇 | 어디에 | 이유 |
|---|---|---|
| **API 키** | 환경변수 (K8s Secret) | 코드·DB·로그에 절대 남지 않아야 한다 |
| **프로파일 카탈로그** (모델명, 파라미터, 단가) | 코드 + 환경변수 오버라이드 (K8s ConfigMap) | 리뷰·버전관리 대상. 변경 이력이 남아야 한다 |
| **직원별 프로파일 선택** | MongoDB (`Employee.llm_profile`) | 런타임에 바뀐다. 직원 추가에 재배포가 필요하면 안 된다 |

DB에는 프로파일 **이름만** 저장한다. `Employee`에 `model="MiniMax-M2.7"`을 직접 저장하면,
모델을 교체할 때 마이그레이션 스크립트를 써야 하고, 존재하지 않는 모델명이 DB에 남는다.

### 8.2 프로파일 카탈로그

```python
# llm/profiles.py
@dataclass(frozen=True)
class LlmProfile:
    name: str
    provider: str            # "minimax" | "anthropic" | ...
    model: str
    temperature: float
    max_tokens: int
    fallback: str | None = None   # 실패 시 넘어갈 프로파일 이름 (1홉만)


DEFAULT_PROFILES: dict[str, LlmProfile] = {
    # 저가 기본값. 분류/판정/짧은 요약 등 중간 산출물 전담
    "cheap":      LlmProfile("cheap",      "minimax", "MiniMax-M2.7", 0.2, 1_500),
    # 구조화 출력 전용. temperature 0 고정, JSON 강제
    "structured": LlmProfile("structured", "minimax", "MiniMax-M2.7", 0.0, 2_000),
    # 사람에게 그대로 노출되는 문장(블로그, 쇼츠 대본)
    "writer":     LlmProfile("writer",     "minimax", "MiniMax-M3",   0.8, 4_000, fallback="cheap"),
    # 긴 컨텍스트 분석 / 도구 사용
    "reasoner":   LlmProfile("reasoner",   "minimax", "MiniMax-M3",   0.3, 8_000, fallback="cheap"),
    # 코드 수정 직원. 가장 비싼 모델을 허용하는 유일한 자리
    "coder":      LlmProfile("coder",      "anthropic", "claude-sonnet-4-5", 0.2, 8_000),
}
```

- 환경변수 `LLM_PROFILES_JSON`으로 전체를 덮어쓸 수 있게 한다 → K8s ConfigMap으로 주입.
- **부팅 시점에 검증한다**: 모든 프로파일의 `provider`가 registry에 존재하고, 해당
  프로바이더의 키가 설정되어 있는지, `fallback` 이름이 카탈로그에 있는지. 하나라도 실패하면
  앱을 띄우지 않는다. 런타임에 첫 호출에서 발견되면 이미 늦다.
- DB 시드 시 `Employee.llm_profile`이 카탈로그에 존재하는지도 검증한다.

### 8.3 직원별 모델 배정 기준

"직원별로 모델을 다르게 둬야 할 것 같은데 잘 모르겠다"에 대한 답은 한 문장이다.
**출력이 사람에게 그대로 노출되는 직원에만 비싼 모델을 준다.**

| 직무 | 프로파일 | 근거 |
|---|---|---|
| `COLLECTOR` | `structured` | 수집·파싱은 코드가 한다. LLM은 분류/정제 보조용. 품질 요구 낮음 |
| `ANALYST` | `structured` | 산출물이 JSON(중간 산출물). temperature 0, 최저가로 충분 |
| `WRITER` | `writer` | 문장 자체가 최종 산출물. 여기서 아끼면 결과물 품질이 바로 떨어진다 |
| `TRADER` | `cheap` | 매매 판단은 규칙 기반 코드. LLM은 사유 설명문만 생성 |
| `ENGINEER` | `coder` | 코드 수정은 실패 비용이 가장 크다. 유일하게 최상위 모델 허용 |

원칙 하나 더: **판단을 LLM에 맡기지 말고, 판단은 코드로 하고 LLM에는 표현을 맡긴다.**
그러면 대부분의 직원이 저가 모델로 충분해진다. 모델 등급을 올려서 해결하려는 문제는
보통 프롬프트나 설계 문제다.

### 8.4 프로바이더 어댑터 (MiniMax 기준)

```python
# llm/providers/base.py
class LlmProvider(Protocol):
    name: str
    async def complete(self, profile: LlmProfile, messages: list[Message]) -> LlmResult: ...
```

MiniMax는 OpenAI 호환 Chat Completions 스키마를 제공하므로, `openai` SDK의 `base_url`만
바꿔서 쓰는 게 가장 코드가 적다.

```python
# llm/providers/minimax.py
client = AsyncOpenAI(
    api_key=settings.minimax_api_key,
    base_url=settings.minimax_base_url,   # 예: https://api.minimax.io/v1
)
```

확인해야 할 사항 (문서로 반드시 검증 — 아래는 2026-08 기준 조사 결과):

- 국제용 호스트는 `api.minimax.io`이고 <cite index="14-1">OpenAI 호환 Chat Completions와 Anthropic Messages 형식 라우트를 함께 제공한다</cite>. 중국 본토 호스트는 별도이므로 리전에 맞는 쪽을 쓴다 (추측: 계정 생성 리전에 따라 키가 호환되지 않을 수 있으니 키 발급처와 호스트를 반드시 일치시킬 것).
- 텍스트 모델은 <cite index="8-1">M3가 표준 티어에서 입력 100만 토큰당 $0.30, 출력 100만 토큰당 $1.20이며, `service_tier`를 priority로 지정하면 1.5배가 과금된다</cite>. <cite index="9-1">M2.7은 2026년 3월 출시된 205K 컨텍스트 모델</cite>이고, <cite index="8-1">M2.7은 priority 티어 대신 2배 가격의 별도 highspeed 변형 모델을 제공한다</cite>.
- <cite index="8-1">출력 토큰 단가가 입력의 4배이므로, 생성량이 많은 작업이 비용을 지배한다</cite>. 따라서 `max_tokens`를 프로파일마다 넉넉하게 두지 말고 실측해서 조인다. 이게 가장 효과가 큰 비용 절감 수단이다.
- <cite index="8-1">선불 종량제 키와 월 구독(Token Plan) 키가 별도로 운영되므로</cite> 어느 쪽 키인지 확인이 필요하다.
- TTS는 토큰이 아니라 <cite index="8-1">입력 문자 수 기준으로 과금되며, 영상·음악·이미지는 각각 클립/트랙/장 단위로 과금된다</cite>. 쇼츠 파이프라인을 붙일 때 텍스트 단가 계산식을 그대로 재사용하면 안 된다.

단가는 계속 바뀌므로(<cite index="11-1">M3 입력 단가는 최근 90일간 20% 하락했다</cite>) **코드에 하드코딩하지 않고 환경변수/ConfigMap에서 읽는다.**

```bash
# 1M 토큰당 USD. 프로파일이 아니라 모델 단위로 관리
LLM_PRICING_JSON='{"MiniMax-M2.7":{"in":0.30,"out":1.20},"MiniMax-M3":{"in":0.30,"out":1.20}}'
USD_KRW_RATE=1380          # 환율도 설정값. 원장은 KRW로 기록
```

### 8.5 비용 기록 흐름

```
워커 → POST /internal/v1/llm/completions (employee_id만)
     → llm/service.py
        1. employees repo에서 employee.llm_profile 조회
        2. profiles.py에서 LlmProfile 해석
        3. providers/registry에서 프로바이더 획득 → 호출
        4. 실패 시 profile.fallback으로 1회 재시도 (Activity에 WARN 기록)
        5. usage(input/output 토큰) 수신
        6. pricing.py: 단가표 × 토큰 → USD → KRW 환산 (순수 함수)
        7. LedgerEntry(category=LLM_COST, amount=계산값) 기록
        8. 응답 반환
```

7번이 자동이라는 게 이 구조의 값어치다. "이번 달 LLM 비용" 질문의 답이 원장 집계에서
자동으로 나오고, 회사 손익에 즉시 반영된다. 워커 개발자가 비용 기록을 잊을 방법이 없다.

`pricing.py`는 I/O가 없는 순수 함수이므로 단위 테스트로 소수점까지 검증한다.
LLM 비용은 소액이 대량 누적되는 항목이라 `Decimal` 정밀도가 실제로 문제가 된다.

### 8.6 키 취급 규칙

- 키는 `Settings`에 `SecretStr`로 담는다. `str`로 담으면 로그·에러 트레이스에 노출된다.
- 예외 메시지에 요청 헤더를 붙이지 않는다. 프로바이더 에러는 상태코드와 프로바이더
  에러코드만 남기고 본문은 요약해서 기록한다.
- `.env`는 `.gitignore`에, `.env.example`만 커밋한다.
- 프론트엔드는 LLM 키를 절대 갖지 않는다. 챗봇도 백엔드 경유다.
  (<cite index="14-1">브라우저 번들은 사용자와 공격자에게 그대로 노출되므로, 인증된 자체 백엔드를 통해 요청을 보내고 키는 시크릿 매니저에 두어야 한다</cite>.)
- 키 로테이션 실습: K8s에서 Secret만 교체하고 Deployment를 롤링 재시작해 무중단 교체를 확인한다.

---

## 9. 로컬 인프라 (docker-compose)

### 9.1 서비스 구성

```yaml
# docker-compose.yml (요지)
services:
  mongo:                  # 단일 노드 replica set (트랜잭션 + change stream 사용 목적)
    image: mongo:7
    command: ["--replSet", "rs0", "--bind_ip_all"]
    ports: ["27017:27017"]
    volumes: [mongo_data:/data/db]
    healthcheck:          # rs 초기화 여부까지 확인
      test: ["CMD", "mongosh", "--quiet", "--eval", "rs.status().ok"]

  mongo-init:             # rs.initiate() 1회 실행 후 종료
    image: mongo:7
    depends_on: { mongo: { condition: service_started } }
    entrypoint: ["bash", "-c", "sleep 3 && mongosh --host mongo --eval 'rs.initiate()' || true"]

  etcd:                   # Milvus 메타 스토어
    image: quay.io/coreos/etcd:v3.5.14
  minio:                  # Milvus 오브젝트 스토어
    image: minio/minio:latest
  milvus:
    image: milvusdb/milvus:v2.4-latest
    command: ["milvus", "run", "standalone"]
    depends_on: [etcd, minio]
    ports: ["19530:19530", "9091:9091"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9091/healthz"]

  redis:                  # EventBus (Phase 4 이후, K8s 다중 replica 대비)
    image: redis:7-alpine

  backend:
    build: { context: ., dockerfile: deploy/docker/backend.Dockerfile }
    env_file: [.env]
    depends_on:
      mongo:  { condition: service_healthy }
      milvus: { condition: service_healthy }
    ports: ["8000:8000"]

  worker:
    build: { context: ., dockerfile: deploy/docker/worker.Dockerfile }
    env_file: [.env]
    depends_on: { backend: { condition: service_healthy } }

  frontend:
    build: { context: ./frontend, dockerfile: ../deploy/docker/frontend.Dockerfile }
    ports: ["5173:80"]

volumes: { mongo_data: {}, milvus_data: {}, minio_data: {} }
```

### 9.2 설계 시 지킬 점

- **`depends_on`에 `condition: service_healthy`를 반드시 쓴다.** 그냥 `depends_on`은
  컨테이너 시작만 기다리고 준비 완료를 기다리지 않는다. Milvus는 부팅이 느려서 이 차이가 크다.
- **Mongo를 단일 노드 replica set으로 띄운다.** standalone은 트랜잭션과 change stream을
  못 쓴다. "작업 완료 + 원장 기록"을 원자적으로 묶으려면 트랜잭션이 필요하고,
  change stream은 Phase 4에서 실시간 이벤트 소스로 쓸 수 있다(Redis 대안).
- **프로파일로 나눈다.** `--profile infra`(DB만), `--profile app`(앱 포함),
  `--profile tools`(mongo-express, attu). 개발 중엔 인프라만 컨테이너로 띄우고
  앱은 호스트에서 직접 실행하는 게 반복 속도가 훨씬 빠르다.
- **개발용 오버라이드는 분리한다.** `docker-compose.override.yml`에 소스 볼륨 마운트와
  `--reload`를 두고, 기본 파일은 프로덕션에 가깝게 유지한다. 그래야 K8s로 옮길 때
  기본 파일을 그대로 번역할 수 있다.
- 호스트에서 실행할 때와 컨테이너에서 실행할 때 접속 주소가 달라진다
  (`localhost:27017` vs `mongo:27017`). 이걸 `.env` 한 벌로 해결하지 말고
  `.env`(호스트용)와 compose의 `environment` 오버라이드(컨테이너용)로 분리한다.

### 9.3 Makefile

```makefile
up:        docker compose --profile infra up -d
up-all:    docker compose --profile infra --profile app up -d --build
down:      docker compose --profile infra --profile app down
clean:     docker compose down -v          # 볼륨까지 삭제 (데이터 소실 주의)
logs:      docker compose logs -f backend
seed:      cd backend && python -m src.scripts.seed
test:      cd backend && pytest tests/unit
test-int:  cd backend && pytest tests/integration   # 인프라 필요
```

---

## 10. Kubernetes 전환 준비

지금 코드를 짤 때 지켜두면 K8s 전환이 설정 파일 작성으로 끝나고, 어기면 코드를 다시 짜야 한다.

### 10.1 지금부터 지킬 것

| 항목 | 규칙 | 어기면 생기는 일 |
|---|---|---|
| 설정 | 환경변수만. 설정 파일을 이미지에 굽지 않는다 | 환경별로 이미지를 따로 빌드해야 한다 |
| 상태 | 프로세스 메모리에 복구 불가 상태 없음 (ADR-008) | replica 2에서 WS 이벤트가 유실된다 |
| 로그 | stdout에 **JSON 한 줄**. 파일로 쓰지 않는다 | 로그 수집기가 파싱 못 한다 |
| 헬스체크 | `/health/live`(의존성 검사 X)와 `/health/ready`(Mongo·Milvus 검사) 분리 | Mongo가 잠깐 느려지면 Pod가 계속 재시작한다 |
| 종료 | SIGTERM 수신 → 새 요청 거부 → 진행 중 작업 마감 → WS 정리 | 롤링 업데이트마다 요청이 끊긴다 |
| 이미지 | 멀티스테이지, non-root 유저, `latest` 태그 금지 | 보안 정책에 막히고 롤백이 불가능해진다 |
| 마이그레이션 | 인덱스 생성은 앱 부팅이 아니라 별도 Job으로 | replica가 동시에 인덱스를 만들며 경합한다 |

`/health/live`와 `/health/ready`를 분리하는 이유는 K8s의 두 프로브가 하는 일이 정반대이기
때문이다. liveness 실패는 **재시작**, readiness 실패는 **트래픽 제외**다. liveness에 DB 검사를
넣으면 DB 장애가 전체 Pod 재시작 폭풍으로 증폭된다.

### 10.2 K8s 리소스 매핑

| 구성요소 | K8s 리소스 | 비고 |
|---|---|---|
| backend | Deployment + Service + Ingress | replica 2부터 Redis EventBus 필수 |
| frontend | Deployment + Service (nginx) | 정적 파일. HPA 불필요 |
| worker (주기 작업) | CronJob | `scheduler.py`를 K8s가 대체. 애플리케이션 스케줄러 제거 |
| worker (상시 작업) | Deployment | 필요할 때만 |
| redis | Deployment + Service | 캐시/버스. 유실 허용이므로 PVC 불필요 |
| mongo / milvus | StatefulSet + PVC (실습) → 관리형 서비스 (실전) | 학습 목적이면 StatefulSet 직접 운영이 배울 게 많다 |
| 설정 | ConfigMap (`LLM_PROFILES_JSON`, `LLM_PRICING_JSON`, RAG 파라미터) | |
| 비밀 | Secret (`MINIMAX_API_KEY`, `WORKER_API_KEY`, Mongo 인증) | |

### 10.3 단계별 실습 경로

```
1. docker-compose로 전체 구동 (Phase 0~7)
2. kind 또는 minikube에 인프라 없이 앱만 배포 (DB는 로컬 compose 유지) — 가장 빨리 배운다
3. Mongo/Milvus를 StatefulSet + PVC로 클러스터 안으로 이전
4. Secret/ConfigMap 분리, 키 로테이션 무중단 교체 실습
5. worker를 CronJob으로 전환하고 APScheduler 제거
6. backend replica 2로 증가 → Redis EventBus 동작 확인 (여기서 ADR-008의 값어치가 드러난다)
7. Ingress + TLS, HPA, resource requests/limits 튜닝
```

2번을 3번보다 먼저 하는 게 중요하다. 앱과 스토리지를 동시에 K8s로 옮기면
문제가 났을 때 원인이 어느 쪽인지 알 수 없다.

---

## 11. RAG 파이프라인

### 11.1 적재 (수집 직원)

```
1. collector 워커: RSS/API/웹에서 원문 수집
2. content_hash로 중복 판정 → 이미 있으면 skip (Activity에 "중복 3건 건너뜀" 기록)
3. POST /internal/v1/knowledge/documents
4. 백엔드 knowledge/service.py:
   a. Mongo에 SourceDocument 저장
   b. chunking.py로 분할 (문단 우선, 목표 500 토큰 / 오버랩 80)
   c. embeddings.py로 배치 임베딩
   d. vector_store.py: doc_id 기준 delete → insert (멱등)
   e. indexed_at, chunk_count 갱신
```

임베딩 호출은 **배치 + 재시도 + 부분 실패 허용**. 한 문서가 실패해도 다음 문서로 진행하고
실패는 `Activity(level=ERROR)`로 남긴다.

### 11.2 질의 (챗봇)

```
1. 사용자 질문 수신
2. 질문 임베딩 → Milvus top_k=8 검색 (필요 시 source_type 필터)
3. 점수 임계값 미달이면 "자료에 없음"으로 즉시 응답 (환각 방지 1차 방어선)
4. 숫자 질문 감지 시 ledger_summary 툴 호출 → 계산된 값을 컨텍스트에 주입
5. LLM 호출: 시스템 프롬프트에
   - 제공된 컨텍스트에만 근거할 것
   - 모든 문장에 [n] 형식 출처 표기
   - 숫자는 컨텍스트에 있는 값만 그대로 인용, 자체 계산·추정 금지
6. 응답 + 인용 청크(doc_id, title, source_url) 함께 반환
```

응답 스키마에 `citations` 배열을 필수로 두면 프론트에서 출처 없는 문장을 즉시 발견할 수 있다.

---

## 12. 프론트엔드 (Three.js)

### 렌더링 전략
- 캐릭터는 처음엔 GLTF 없이 **박스 + 구 조합 프리미티브**로 시작한다.
  모델링에 시간을 쓰기 시작하면 프로젝트가 거기서 멈춘다. 형태는 Phase 후반에 교체.
- 상태는 색으로: `WORKING` 초록 / `IDLE` 회색 / `BLOCKED` 주황 / `ERROR` 빨강 / `OFFLINE` 반투명.
- 말풍선은 WebGL 텍스처가 아니라 `CSS2DRenderer`로 DOM 라벨을 띄운다. 한글 폰트·줄바꿈이 공짜.
- 이동은 `desk` 좌표 사이 `lerp`. 물리엔진·경로탐색은 넣지 않는다.

### 데이터 흐름
```
진입 → GET /office/snapshot → officeStore 초기화 → 씬 구성
     → WS 연결 → 이벤트 수신 → officeStore 패치 → 다음 프레임에 반영
     → WS 끊김 → 지수 백오프 재연결 → 재연결 성공 시 snapshot 재조회 (상태 정합 복구)
```

마지막 줄이 중요하다. 재연결 후 이벤트만 이어받으면 끊긴 동안의 변경이 영구히 유실된다.

---

## 13. 테스트 전략 (Classist)

경계(Mongo/Milvus/LLM/HTTP/시계)만 대체하고, 그 안쪽은 전부 실제 객체를 쓴다.

| 계층 | 대상 | 방식 |
|---|---|---|
| Unit | `state_machine`, `chunking`, `renderer`, `pricing` | 순수 함수, mock 0개 |
| Unit | service 로직 | `tests/fakes`의 InMemory repository 사용 (DB 불필요) |
| Integration | repository 구현체 | testcontainers 실제 Mongo |
| Integration | `knowledge` service | 실제 Milvus + 임베딩만 fake |
| E2E | 워커 작업 1건 → snapshot 반영까지 | httpx AsyncClient |

Repository를 도입한 덕에 **service 테스트에서 DB가 사라진다.** 이게 ADR-004의 실질적 보상이다.
단, InMemory fake와 실제 Mongo 구현의 동작이 갈라지면 테스트가 거짓말을 하게 되므로,
**동일한 테스트 스위트를 두 구현에 모두 돌린다**(pytest `params`로 fake/real을 주입).
이걸 안 하면 fake가 서서히 실제와 달라지고, 통과하는 테스트와 깨지는 프로덕션이 공존한다.

반드시 있어야 하는 테스트 (한 문장으로 보호 대상을 말할 수 있는 것들):

```
summary_reflects_reversal_entry_when_entry_is_reversed()
renderer_raises_when_placeholder_is_unknown()
renderer_raises_when_unsubstituted_placeholder_remains()
task_rejects_transition_to_running_when_already_finished()
document_is_skipped_when_content_hash_already_exists()
reindex_replaces_chunks_without_duplicating_when_document_is_reingested()
chat_answers_not_found_when_no_chunk_passes_score_threshold()
internal_endpoint_returns_401_when_worker_key_is_missing()

# LLM 게이트웨이
app_fails_to_start_when_profile_references_unknown_provider()
app_fails_to_start_when_provider_key_is_missing()
completion_uses_profile_of_requesting_employee()
completion_records_llm_cost_entry_when_call_succeeds()
completion_falls_back_to_secondary_profile_when_primary_fails()
cost_is_calculated_from_pricing_table_not_from_provider_response()
```

마지막 테스트가 중요하다. 프로바이더가 응답에 비용을 담아 보내더라도 그 값을 신뢰하지 않고
자체 단가표로 계산한다. 외부 값을 원장에 그대로 넣으면 숫자 규칙이 외부에 위임된다.

LLM 응답 텍스트는 스냅샷하지 않는다. 검증 대상은 "출처 배열이 비어있지 않다",
"임계값 미달 시 not_found 코드" 같은 구조적 성질.

---

## 14. 구현 단계

각 Phase는 **동작하는 상태로 끝난다**. Phase 경계에서 항상 실행 가능해야 한다.

| Phase | 산출물 | 완료 조건 |
|---|---|---|
| 0 | 모노레포 스캐폴딩, docker-compose(mongo RS/milvus), config, `/health/live·ready` | `make up && curl /health/ready` 200 |
| 1 | `employees` 도메인 (router→service→repository) + 시드 | 직원 5명 조회, service 테스트가 DB 없이 통과 |
| 2 | `tasks` + `activities` + 내부 API + 워커 하네스 | 더미 워커가 작업 1건 완주 |
| 3 | `ledger` 기록/집계/렌더러 + 무결성 테스트 | §13 테스트 목록 통과 |
| 4 | `llm` 게이트웨이 (프로파일·단가·비용 기록) + MiniMax 어댑터 | 워커가 프록시로 응답 받고 `LLM_COST`가 원장에 쌓임 |
| 5 | `realtime` EventBus(InMemory) + WS 허브 + snapshot API | 이벤트가 브라우저 콘솔에 도착 |
| 6 | 프론트 Three.js 씬 + 아바타 + 말풍선 + 원장 패널 | 실시간으로 캐릭터 상태 변화 |
| 7 | `knowledge` + collector 직원 + Milvus 적재 | 문서 수집 → 벡터 검색 동작 |
| 8 | `chat` RAG 챗봇 + 출처 인용 + ledger 툴 | 출처 없는 답변이 나오지 않음 |
| 9 | 스케줄러, 재시도, 구조적 JSON 로깅, graceful shutdown | 하루 무인 운영 |
| 10 | K8s: 앱만 kind에 배포 (DB는 compose 유지) | Pod 2개가 Ingress 뒤에서 응답 |
| 11 | K8s: StatefulSet DB 이전, Secret/ConfigMap 분리, CronJob 워커 | 클러스터 안에서 전체 동작 |
| 12 | RedisEventBus 전환 → backend replica 2 | 어느 Pod에 붙어도 이벤트 수신 |

Phase 6까지가 "관제실", 7~8이 "RAG 학습", 9~12가 "운영·인프라 학습".

순서에 관한 두 가지 주의:

1. **Phase 3(숫자 규칙)을 건너뛰지 않는다.** RAG가 훨씬 재미있어 보이지만, 원장을 나중에
   넣으면 요약문·챗봇·프론트를 전부 다시 짠다.
2. **Phase 4(LLM 게이트웨이)를 워커 구현보다 먼저 한다.** 워커가 프로바이더를 직접 호출하는
   코드를 한 번 쓰면, 나중에 프록시로 바꿀 때 모든 워커를 고쳐야 하고 그 사이에 키가
   여러 곳에 퍼진다.

---

## 15. 환경 변수 (.env.example)

```bash
# ─── app ────────────────────────────────────────────────
APP_ENV=local                     # local | staging | prod
LOG_LEVEL=INFO
LOG_FORMAT=json                   # 로컬은 console 허용, 그 외 json 고정
CORS_ORIGINS=http://localhost:5173

# ─── mongo ──────────────────────────────────────────────
MONGO_URI=mongodb://localhost:27017/?replicaSet=rs0
MONGO_DB=mini_company

# ─── milvus ─────────────────────────────────────────────
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=knowledge_chunks

# ─── redis (EventBus) ───────────────────────────────────
EVENT_BUS=memory                  # memory | redis  (replica ≥ 2면 redis 필수)
REDIS_URL=redis://localhost:6379/0

# ─── internal auth ──────────────────────────────────────
WORKER_API_KEY=change-me          # [SECRET]

# ─── LLM: 키 (프로바이더 단위, 전부 SECRET) ──────────────
MINIMAX_API_KEY=                  # [SECRET] 기본 프로바이더
MINIMAX_BASE_URL=https://api.minimax.io/v1
MINIMAX_GROUP_ID=                 # 일부 엔드포인트에서 요구 (추측: 텍스트 완성엔 불필요)
ANTHROPIC_API_KEY=                # [SECRET] coder 프로파일용, 없으면 해당 프로파일 비활성
OPENAI_API_KEY=                   # [SECRET] 임베딩용(선택)

# ─── LLM: 프로파일 카탈로그 (ConfigMap 대상, 비밀 아님) ──
LLM_DEFAULT_PROFILE=cheap
LLM_PROFILES_JSON=                # 비우면 코드의 DEFAULT_PROFILES 사용
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2

# ─── LLM: 단가표 (1M 토큰당 USD, 모델 단위) ─────────────
LLM_PRICING_JSON='{"MiniMax-M2.7":{"in":0.30,"out":1.20},"MiniMax-M3":{"in":0.30,"out":1.20}}'
USD_KRW_RATE=1380                 # 원장은 KRW 기록. 환율도 설정값
LLM_DAILY_COST_LIMIT_KRW=5000     # 초과 시 프록시가 거부 (폭주 방어)

# ─── embeddings ─────────────────────────────────────────
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536

# ─── rag ────────────────────────────────────────────────
RAG_TOP_K=8
RAG_SCORE_THRESHOLD=0.35
CHUNK_TARGET_TOKENS=500
CHUNK_OVERLAP_TOKENS=80
```

### 설정 분류 규칙 (K8s 전환 시 그대로 매핑)

- `[SECRET]` 표시가 붙은 것만 K8s **Secret**. 나머지는 전부 **ConfigMap**.
- 이 구분을 `.env.example`에 주석으로 미리 박아두면, K8s 매니페스트를 쓸 때 판단이 필요 없다.
- 코드에서는 `Settings`의 필드 타입으로 강제한다: 비밀은 `SecretStr`, 나머지는 일반 타입.
  타입만 봐도 어디로 가야 하는지 알 수 있다.

### 부팅 시 검증 항목 (실패하면 앱을 띄우지 않는다)

1. `EMBEDDING_DIM`이 기존 Milvus 컬렉션의 dim과 일치하는가
   — 불일치 시 재인덱싱 없이 돌면 검색 품질만 조용히 망가진다. 가장 발견이 어려운 버그다.
2. 모든 LLM 프로파일의 `provider`가 registry에 있고, 그 프로바이더 키가 설정되어 있는가
3. 모든 프로파일의 `model`이 `LLM_PRICING_JSON`에 단가를 가지고 있는가
   — 단가가 없으면 비용을 0으로 기록하게 되고, 그건 숫자 규칙 위반이다
4. `fallback` 프로파일 이름이 카탈로그에 존재하는가 (순환 참조도 검사)
5. `EVENT_BUS=memory`인데 replica가 2 이상일 가능성 — 감지 불가하므로 로그에 경고 1회 출력
6. `APP_ENV != local`인데 `WORKER_API_KEY == change-me` → 즉시 실패

3번이 특히 중요하다. "단가를 모르는 모델은 호출하지 않는다"를 부팅 시점에 강제하면,
LLM 비용이 원장에서 누락되는 경로가 원천적으로 사라진다.