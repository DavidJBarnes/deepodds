FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.7.2 /uv /usr/local/bin/uv

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONPATH="/app/backend"

WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --no-dev --no-install-project

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/carry ./carry
COPY backend/longshot ./longshot
COPY backend/entrypoint.sh ./
RUN chmod +x entrypoint.sh
RUN uv sync --no-dev

EXPOSE 8000

CMD ["./entrypoint.sh"]
