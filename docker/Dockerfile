# Один базовый образ для всех Python-сервисов стенда.
# Сервис выбирается командой в docker-compose.yml: python -m <service>.main
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY . .
# Только рантайм-зависимости всех пакетов workspace, без dev-группы
RUN uv sync --frozen --no-dev --all-packages --no-editable \
    --python /usr/local/bin/python

FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home --uid 1000 stand
COPY --from=builder /opt/venv /opt/venv
USER stand
WORKDIR /app
