COMPOSE := docker compose
PROFILES := --profile infra --profile app

.PHONY: up up-all down clean logs dev indexes seed test test-int test-e2e test-worker lint fmt worker-demo scheduler dev-front test-front k8s-up k8s-images k8s-secret k8s-deploy k8s-deploy-full k8s-status k8s-logs k8s-rotate-key k8s-down

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

worker-demo: ## 수집 워커 1회 실행. 백엔드(up-all 또는 dev)와 시드가 먼저 필요하다.
	cd workers && .venv/bin/python -m src.employees.collector

scheduler: ## 주기 실행(기본: 매일 11시). Ctrl+C로 종료. K8s에서는 CronJob이 대체한다.
	cd workers && .venv/bin/python -m src.scheduler

lint: ## backend와 workers 양쪽. 한쪽만 검사하면 다른 쪽이 조용히 썩는다.
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd workers && .venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
	cd workers && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

# ─── Kubernetes (Phase 10~11) ────────────────────────────────
KIND_CLUSTER := mini-company
K8S_NS := mini-company
IMAGE_TAG := 0.1.0

k8s-up: ## kind 클러스터 생성 + ingress-nginx 설치
	kind create cluster --config deploy/k8s/kind-cluster.yaml
	# 노드가 레지스트리 TLS를 검증하지 못하는 망(기업 프록시)에서는 여기서 막힌다.
	# 이미지 apply보다 먼저 신뢰를 심어야 첫 pull부터 성공한다.
	./deploy/k8s/trust-proxy-ca.sh $(KIND_CLUSTER)
	kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.3/deploy/static/provider/kind/deploy.yaml
	# rollout status를 쓴다. `kubectl wait`은 Pod가 아직 생성되지 않았으면
	# "no matching resources found"로 즉시 실패한다.
	kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=180s

k8s-images: ## 이미지 빌드 후 kind에 로드. 레지스트리가 없으므로 직접 넣는다.
	docker build -t mini-company/backend:$(IMAGE_TAG) -f deploy/docker/backend.Dockerfile .
	docker build -t mini-company/frontend:$(IMAGE_TAG) -f deploy/docker/frontend.Dockerfile .
	docker build -t mini-company/worker:$(IMAGE_TAG) -f deploy/docker/worker.Dockerfile .
	kind load docker-image --name $(KIND_CLUSTER) \
		mini-company/backend:$(IMAGE_TAG) \
		mini-company/frontend:$(IMAGE_TAG) \
		mini-company/worker:$(IMAGE_TAG)

k8s-secret: ## Secret 생성. 커밋하지 않는 값이라 매니페스트가 아니라 명령으로 만든다.
	kubectl create namespace $(K8S_NS) --dry-run=client -o yaml | kubectl apply -f -
	# .env가 있으면 LLM 키를 거기서 가져온다. 셸이 읽어 kubectl에 넘길 뿐 파일로
	# 남기지 않는다. 키가 없으면 빈 값이 들어가고, APP_ENV=staging/prod인 백엔드는
	# 부팅을 거부한다 — 의도된 동작이다(§8.2). 로컬 overlay는 APP_ENV=local이라 뜬다.
	#
	# `. ./.env`로 source하지 않는다. .env는 셸 스크립트가 아니라서 따옴표 없는
	# `EMPLOYEE_NAME=수집가 노아` 같은 줄을 만나면 "노아: command not found"가 난다.
	# 필요한 키만 뽑아내면 파일의 나머지 내용과 무관해진다.
	@MINIMAX="$$(sed -n 's/^MINIMAX_API_KEY=//p' .env 2>/dev/null | tail -1)"; \
	ANTHROPIC="$$(sed -n 's/^ANTHROPIC_API_KEY=//p' .env 2>/dev/null | tail -1)"; \
	OPENAI="$$(sed -n 's/^OPENAI_API_KEY=//p' .env 2>/dev/null | tail -1)"; \
	MINIMAX_API_KEY="$${MINIMAX:-$$MINIMAX_API_KEY}"; \
	ANTHROPIC_API_KEY="$${ANTHROPIC:-$$ANTHROPIC_API_KEY}"; \
	OPENAI_API_KEY="$${OPENAI:-$$OPENAI_API_KEY}"; \
	kubectl -n $(K8S_NS) create secret generic backend-secret \
		--from-literal=WORKER_API_KEY="$$(openssl rand -hex 32)" \
		--from-literal=MINIMAX_API_KEY="$${MINIMAX_API_KEY:-}" \
		--from-literal=ANTHROPIC_API_KEY="$${ANTHROPIC_API_KEY:-}" \
		--from-literal=OPENAI_API_KEY="$${OPENAI_API_KEY:-}" \
		--dry-run=client -o yaml | kubectl apply -f -

k8s-deploy: ## Phase 10 — 앱만 배포(DB는 호스트 compose). make up이 먼저 필요하다.
	kubectl apply -k deploy/k8s/overlays/local
	kubectl -n $(K8S_NS) rollout status deployment/backend --timeout=180s
	kubectl -n $(K8S_NS) rollout status deployment/frontend --timeout=120s

k8s-deploy-full: ## Phase 11 — DB까지 클러스터 안으로(StatefulSet + CronJob).
	kubectl apply -k deploy/k8s/overlays/prod
	kubectl -n $(K8S_NS) rollout status statefulset/mongo --timeout=300s
	kubectl -n $(K8S_NS) rollout status deployment/backend --timeout=300s

k8s-status: ## Pod·Service·Ingress 상태
	kubectl -n $(K8S_NS) get pods,svc,ingress,statefulset,cronjob

k8s-logs: ## backend 로그(JSON 한 줄)
	kubectl -n $(K8S_NS) logs -l app=backend --tail=50 -f

# k8s-secret이 매번 새 WORKER_API_KEY를 발급하므로 로테이션은 "다시 만들고 재시작"이다.
# Secret이 바뀌어도 Pod는 알아서 다시 읽지 않는다 — envFrom은 프로세스 시작 시점에만
# 평가된다. 그래서 재시작이 필요하고, 롤링이라 요청은 끊기지 않는다(§8.6).
k8s-rotate-key: k8s-secret ## 키 로테이션 무중단 교체 실습(§8.6)
	kubectl -n $(K8S_NS) rollout restart deployment/backend
	kubectl -n $(K8S_NS) rollout status deployment/backend --timeout=180s

k8s-down: ## 클러스터 삭제
	kind delete cluster --name $(KIND_CLUSTER)
