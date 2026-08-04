# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /build
COPY backend/pyproject.toml ./
COPY backend/src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim

# non-root. UID를 고정해 K8s의 runAsUser와 맞춘다.
RUN useradd --create-home --uid 10001 app

COPY --from=builder /install /usr/local

WORKDIR /app
USER app

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
