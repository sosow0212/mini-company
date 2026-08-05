COMPOSE := docker compose
PROFILES := --profile infra --profile app

.PHONY: up up-all down clean logs dev indexes seed test test-int test-e2e test-worker lint fmt worker-demo

up: ## 인프라(mongo/milvus)만 띄운다. 앱은 make dev로 호스트에서 실행.
	$(COMPOSE) --profile infra up -d

up-all: ## 인프라 + 백엔드 컨테이너까지 전부 띄운다.
	$(COMPOSE) --profile app up -d --build

down:
	$(COMPOSE) $(PROFILES) down

clean: ## 볼륨까지 삭제한다. 데이터 소실 주의.
	$(COMPOSE) $(PROFILES) down -v

logs:
	$(COMPOSE) logs -f backend

VENV := backend/.venv/bin

dev: ## 호스트에서 백엔드 실행 (핫리로드). cwd를 루트로 둬야 .env를 찾는다.
	$(VENV)/uvicorn src.main:app --reload --app-dir backend --port 8000

indexes: ## 인덱스 생성. K8s에서는 Job으로 돈다.
	cd backend && .venv/bin/python -m src.scripts.create_indexes

seed: indexes ## 직원 5명 시드 (멱등)
	cd backend && .venv/bin/python -m src.scripts.seed

test: ## 단위 테스트. 인프라 불필요.
	cd backend && .venv/bin/pytest tests/unit

test-int: ## 통합 테스트. 인프라 필요(make up).
	cd backend && .venv/bin/pytest tests/integration

test-e2e: ## e2e 테스트. 인프라 필요(make up).
	cd backend && .venv/bin/pytest tests/e2e

test-worker: ## 워커 단위 테스트. 인프라 불필요.
	cd workers && .venv/bin/pytest tests

dev-front: ## 프론트 개발 서버. /api를 백엔드로 프록시하므로 백엔드가 먼저 필요하다.
	cd frontend && npm run dev

test-front: ## 프론트 단위 테스트 + 타입체크.
	cd frontend && npm run typecheck && npm test

worker-demo: ## 더미 수집 워커 1회 실행. 백엔드(up-all 또는 dev)와 시드가 먼저 필요하다.
	cd workers && .venv/bin/python -m src.employees.collector

lint: ## backend와 workers 양쪽. 한쪽만 검사하면 다른 쪽이 조용히 썩는다.
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd workers && .venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
	cd workers && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
