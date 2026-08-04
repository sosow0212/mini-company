# mini-company

AI 직원(에이전트)이 수행한 작업을 3D 오피스로 시각화하고, 수집한 데이터를 RAG로 적재해
챗봇으로 질의하는 학습용 시스템.

- 설계: [`docs/PROJECT_BLUEPRINT.md`](docs/PROJECT_BLUEPRINT.md)
- 에이전트 코딩 규칙: [`AGENTS.md`](AGENTS.md)

## 현재 진행 상황

Phase 0 완료 — 스캐폴딩, 인프라(Mongo replica set / Milvus), 설정, 헬스 프로브.

## 실행

```bash
cp .env.example .env

# 1) 인프라만 컨테이너로 (개발 중 권장)
make up
python3 -m venv backend/.venv && backend/.venv/bin/pip install -e 'backend[dev]'
make dev
curl -s localhost:8000/health/ready

# 2) 백엔드까지 컨테이너로
make up-all
curl -s localhost:8000/health/ready
```

`make up` 직후 Milvus는 부팅에 1분 가까이 걸린다. `docker compose ps`로 `healthy`를 확인한다.

```bash
make test     # 단위 테스트 (인프라 불필요)
make lint     # ruff
make down     # 정지
make clean    # 볼륨까지 삭제
```

## 포트

| 포트 | 서비스 |
|---|---|
| 8000 | backend |
| 27017 | mongo (replica set `rs0`) |
| 19530 | milvus gRPC |
| 9091 | milvus `/healthz` |

## Mongo 접속 주소가 두 벌인 이유

replica set 멤버가 `mongo:27017`로 등록돼 있어서, 호스트에서 `?replicaSet=rs0`로 붙으면
드라이버가 컨테이너 이름을 해석하려다 서버 선택에 실패한다.

- 호스트 (`.env`): `mongodb://localhost:27017/?directConnection=true`
- 컨테이너 (compose `environment`): `mongodb://mongo:27017/?replicaSet=rs0`

`directConnection=true`로도 replica set 멤버에 직결되므로 트랜잭션은 그대로 쓸 수 있다.
