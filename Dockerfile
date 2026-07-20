# Stage 1: Build virtual environment
FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY requirements.txt requirements-dev.txt ./

# Build production venv
RUN uv venv /opt/venv-prod
RUN uv pip install --python /opt/venv-prod/bin/python -r requirements.txt

# Build development venv (includes dev dependencies)
RUN uv venv /opt/venv-dev
RUN uv pip install --python /opt/venv-dev/bin/python -r requirements.txt -r requirements-dev.txt

# Stage 2: Development runtime (hot-reloading, dev dependencies)
FROM python:3.12-slim AS development

WORKDIR /app

COPY --from=builder /opt/venv-dev /opt/venv
COPY alembic.ini /app/
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH"

# Development command runs uvicorn with reload
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Stage 3: Production runtime (lightweight, secure, rootless)
FROM python:3.12-slim AS production

WORKDIR /app

# Create non-root system user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -m -s /sbin/nologin appuser

# Only copy runtime dependencies (re-install prod only for final layer)
COPY --from=builder /opt/venv-prod /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH"

# Copy source code and change ownership
COPY --chown=appuser:appgroup src/ /app/src/
COPY --chown=appuser:appgroup alembic.ini /app/

USER appuser

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
