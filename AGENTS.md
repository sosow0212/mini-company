# AGENTS.md — mini-company

이 저장소에서 코드를 작성·수정하는 모든 에이전트(Claude Code, Codex, Cursor)가 따르는 규칙.
상세 설계는 `docs/PROJECT_BLUEPRINT.md` 참조. 충돌 시 이 파일이 우선한다.

## 프로젝트 한 줄 요약

AI 직원(에이전트)들이 실제로 수행한 작업을 3D 오피스로 시각화하고, 수집한 데이터를
Milvus RAG로 적재해 챗봇으로 질의하는 학습용 시스템. FastAPI + MongoDB + Milvus + Three.js.

## 절대 규칙 (위반 시 작업 중단하고 사용자에게 확인)

1. **숫자는 LLM이 타이핑하지 않는다.** 화면·요약문·챗봇 답변의 모든 수치는
   `ledger_entries`를 서버가 aggregate한 값이어야 한다. 워커/LLM은 원시 트랜잭션만 기록한다.
   요약문에는 `{{ledger.*}}` 플레이스홀더만 쓰고 서버가 치환한다.
2. **`Activity`와 `LedgerEntry`는 append-only.** UPDATE/DELETE 코드를 작성하지 않는다.
   정정은 `reverses_id`를 가진 반대 부호 엔트리로 처리한다.
3. **워커는 DB에 직접 접근하지 않는다.** `/internal/v1/*` API만 호출한다.
   워커 코드에 `motor`, `pymongo`, `pymilvus` import가 등장하면 설계 위반이다.
4. **프론트엔드는 수치를 계산하지 않는다.** 서버가 내려준 문자열을 렌더링만 한다.
   (3D 좌표 보간은 예외)
5. **금액은 `Decimal`/`Decimal128`.** `float`로 통화를 다루지 않는다.
6. **LLM 호출은 백엔드 프록시(`/internal/v1/llm/completions`)만 사용한다.**
   워커·프론트엔드에서 프로바이더 SDK를 직접 호출하지 않는다.
7. **API 키를 코드·DB·로그·테스트 픽스처에 넣지 않는다.** 환경변수 + `SecretStr`만 사용한다.
   `Employee`에는 모델명이 아니라 프로파일 **이름**만 저장한다.
8. **LLM 비용은 자체 단가표로 계산한다.** 프로바이더 응답의 비용 값을 원장에 그대로 넣지 않는다.
9. **커밋하지 않는다.** 스테이징·커밋·푸시는 사용자가 직접 한다.
10. **요청받지 않은 기능을 추가하지 않는다.** 개선 아이디어는 코드가 아니라 말로 제안한다.

## 코드 컨벤션

### 백엔드 (Python 3.12+, FastAPI)

- 도메인별 패키지 구조: `router / schemas / models / repository / service / dependencies / constants / exceptions`.
  **필요한 파일만 만든다.** 내용이 없는 파일을 관례상 생성하지 않는다.
- 레이어 책임 (`router → service → repository → models`):
  - `router.py` — HTTP 파싱과 응답 변환만. 비즈니스 로직 0줄.
  - `service.py` — 비즈니스 로직. **Beanie 쿼리 API(`find`/`insert`/`aggregate`) 사용 금지.**
  - `repository.py` — Beanie 쿼리는 여기서만. 비즈니스 판단·예외 발생 금지, `None` 반환.
  - `models.py` — Beanie `Document`. API에 그대로 노출 금지.
  - `schemas.py` — Pydantic DTO. 응답은 `ApiModel`(camelCase alias) 상속.
- Repository는 DI로 주입한다. 테스트에서 `dependency_overrides`로 fake 교체가 가능해야 한다.
- 모든 I/O는 `async`. 동기 블로킹 라이브러리 사용 금지.
- **12-Factor 준수** (K8s 전환 예정):
  - 설정은 환경변수만. 설정 파일을 읽거나 이미지에 굽지 않는다.
  - 로그는 stdout에 JSON 한 줄. 파일에 쓰지 않는다.
  - 프로세스 메모리에 복구 불가능한 상태를 두지 않는다. 브로드캐스트는 `EventBus`를 경유한다.
  - `/health/live`에는 외부 의존성 검사를 넣지 않는다. 의존성 검사는 `/health/ready`에만.
  - SIGTERM 핸들러로 graceful shutdown을 구현한다.
- 타입 힌트 100%. `Any`를 쓸 경우 이유를 주석으로 남긴다.
- router에서 `HTTPException`을 던지지 않는다. 도메인 예외(`AppError` 하위)를 던지고
  `main.py`의 전역 핸들러가 HTTP로 번역한다.
- 순수 로직(상태 전이, 청킹, 플레이스홀더 치환)은 I/O 없는 별도 모듈로 분리한다.
  단, **분리를 위한 분리는 하지 않는다** — 호출처가 하나이고 20줄 미만이면 그대로 둔다.

### 프론트엔드 (TypeScript, Three.js, Vite)

- 프레임워크 없이 시작한다. React 도입은 UI 상태가 실제로 복잡해진 뒤에 판단.
- `scene/`(3D)과 `ui/`(DOM)를 섞지 않는다. 말풍선·패널은 `CSS2DRenderer`/DOM 담당.
- `any` 금지. 백엔드 응답 타입은 `api/types.ts`에 정의한다.
- WS 재연결 성공 시 반드시 `/office/snapshot`을 재조회해 상태를 복구한다.

### 네이밍

- 도메인 용어는 블루프린트 §1 표를 따른다. `Agent`가 아니라 `Employee`.
- Python `snake_case`, TypeScript `camelCase`, API 응답 `camelCase`.

### 인프라 (docker-compose / K8s)

- 인프라는 `docker-compose.yml`로 관리한다. 로컬에서 DB를 직접 설치하는 안내를 하지 않는다.
- `depends_on`에는 반드시 `condition: service_healthy`를 붙인다. healthcheck 없는 서비스 금지.
- Mongo는 단일 노드 replica set(`--replSet rs0`)으로 띄운다. standalone 금지
  (트랜잭션·change stream 사용 불가).
- 개발용 볼륨 마운트와 `--reload`는 `docker-compose.override.yml`에만 둔다.
  기본 compose 파일은 프로덕션에 가깝게 유지해 K8s 매니페스트로 번역 가능하게 한다.
- Dockerfile은 멀티스테이지 + non-root 유저. 베이스 이미지에 `latest` 태그 금지.
- K8s 매니페스트는 `deploy/k8s/base` + `overlays/{local,prod}` (kustomize)로 작성한다.
- 새 환경변수를 추가할 때 `.env.example`에 `[SECRET]` 여부를 주석으로 표시한다.
  이 표시가 K8s Secret / ConfigMap 분류의 유일한 근거다.

### LLM

- 프로파일 카탈로그는 `llm/profiles.py` + `LLM_PROFILES_JSON` 오버라이드로만 정의한다.
  모델명을 도메인 코드에 하드코딩하지 않는다.
- 단가는 `LLM_PRICING_JSON`에서 읽는다. 코드에 단가 상수를 넣지 않는다(자주 바뀐다).
- 단가표에 없는 모델은 호출을 거부한다. 부팅 시 검증에서 걸러야 한다.
- 새 프로바이더를 추가할 때는 `providers/base.py`의 `LlmProvider` Protocol만 구현하고,
  `registry.py`에 등록한다. 도메인 service를 수정할 일이 없어야 한다.
- 프로바이더 에러를 로깅할 때 요청 헤더·본문 전체를 남기지 않는다(키 노출).

## 테스트

`test-classist` 스킬 규칙을 따른다. 요약:

- 경계(Mongo/Milvus/LLM/HTTP/시계/랜덤)만 대체한다. 내부 협력 객체는 실제 객체를 쓴다.
- service 테스트는 `tests/fakes`의 InMemory repository를 쓴다 (mock 객체가 아니라 실제 구현체).
- repository 테스트 스위트는 fake와 실제 Mongo 구현 **양쪽에 동일하게** 돌린다.
  fake만 통과하는 테스트는 거짓 안전감을 준다.
- 검증은 반환값과 관찰 가능한 상태로 한다. `assert_called_with`를 주 검증 수단으로 쓰지 않는다.
- 테스트 이름은 행위를 서술한다: `<subject>_<expected_behavior>_when_<condition>`.
- LLM 출력 텍스트를 스냅샷하지 않는다. 구조적 성질(출처 존재, 에러 코드)을 검증한다.
- 스펙에서 실패하는 테스트를 먼저 쓰고 구현한다. "이 파일에 대한 테스트 짜줘"는 금지.

## 커뮤니케이션 규칙

- 모든 응답은 **한국어**로 한다.
- 확인되지 않은 추론은 문장에 `(추측)`을 명시한다.
- 코드를 설명할 때는 개선 제안보다 **현재 구현이 어떻게 동작하는지 사실 위주로** 기술한다.
- 리뷰는 문제가 있는 부분만 핀포인트로 지적한다. 전체 요약 나열은 하지 않는다.
- 기능 명세를 바꾸지 않는 범위에서만 성능·가독성 개선을 제안한다.

## 자주 하는 실수 (체크리스트)

작업을 마치기 전에 확인한다.

- [ ] 새로 만든 파일이 실제로 내용을 가지고 있는가 (빈 껍데기 파일 없음)
- [ ] `service.py`에 Beanie 쿼리가 새로 들어가지 않았는가
- [ ] `/internal/*` 라우터 전체에 `require_worker_key`가 걸려 있는가
- [ ] 새 수치 필드를 추가했다면 그 값이 ledger aggregate에서 나오는가
- [ ] 워커 코드에 DB 드라이버 또는 LLM SDK import가 없는가
- [ ] 응답 스키마에 금액이 문자열로 직렬화되는가
- [ ] 문서 재적재 시 Milvus 청크가 중복되지 않는가 (`doc_id` delete 후 insert)
- [ ] 새 도메인 예외가 `main.py` 핸들러에서 올바른 상태코드로 번역되는가
- [ ] 새 환경변수가 `.env.example`에 `[SECRET]` 표시와 함께 추가되었는가
- [ ] 새 LLM 프로파일/모델이 `LLM_PRICING_JSON`에 단가를 가지고 있는가
- [ ] 프로세스 메모리에 상태를 새로 두지 않았는가 (replica 2에서 깨지지 않는가)
- [ ] 새 compose 서비스에 healthcheck가 있는가