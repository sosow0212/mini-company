COMPOSE := docker compose
PROFILES := --profile infra --profile app

.PHONY: up up-all down clean logs dev test lint fmt

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

test:
	cd backend && .venv/bin/pytest

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
