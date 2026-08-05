# syntax=docker/dockerfile:1
FROM node:22-alpine AS builder

WORKDIR /build
# 의존성 레이어를 소스와 분리해 캐시가 살아남게 한다.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src
COPY frontend/tests ./tests
# 타입 오류가 있는 이미지를 만들지 않는다.
RUN npx tsc --noEmit && npx vite build

# nginx-unprivileged: 마스터 프로세스도 non-root로 돈다(AGENTS.md 인프라 규칙).
FROM nginxinc/nginx-unprivileged:1.29-alpine

COPY --from=builder /build/dist /usr/share/nginx/html
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
