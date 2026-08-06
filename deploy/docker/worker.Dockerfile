# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /build
COPY workers/pyproject.toml ./
COPY workers/src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim

# non-root. backend와 같은 UID를 쓴다 — K8s의 runAsUser를 한 값으로 맞출 수 있다.
RUN useradd --create-home --uid 10001 app

COPY --from=builder /install /usr/local

WORKDIR /app
USER app

# stdout을 버퍼링하지 않는다. 컨테이너 로그는 파이프로 나가서 기본이 블록 버퍼링이고,
# 그러면 종료 직전 로그(graceful shutdown 기록)가 유실될 수 있다.
ENV PYTHONUNBUFFERED=1

# 기본은 스케줄러(상시 프로세스). 한 번만 실행하려면 compose/K8s에서 command를
# `python -m src.employees.collector`로 덮는다 — CronJob이 그렇게 쓴다(§10.2).
CMD ["python", "-m", "src.scheduler"]
