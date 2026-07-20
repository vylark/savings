# Stage 1: Base builder
FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY requirements.txt requirements-dev.txt ./

# Stage 1a: Development builder (builds dev venv at /opt/venv)
FROM builder AS dev-builder
RUN uv venv /opt/venv
RUN uv pip install --python /opt/venv/bin/python -r requirements.txt -r requirements-dev.txt

# Stage 1b: Production builder (builds prod venv at /opt/venv)
FROM builder AS prod-builder
RUN uv venv /opt/venv
RUN uv pip install --python /opt/venv/bin/python -r requirements.txt

# Stage 2: Development runtime (hot-reloading, dev dependencies)
FROM python:3.12-slim AS development

WORKDIR /app

COPY --from=dev-builder /opt/venv /opt/venv
COPY alembic.ini /app/
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

# Development command runs uvicorn with reload
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Stage 3: Production runtime (lightweight, secure, rootless)
FROM python:3.12-slim AS production

WORKDIR /app

# Create non-root system user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -m -s /sbin/nologin appuser

# Only copy runtime dependencies
COPY --from=prod-builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

# Copy source code and change ownership
COPY --chown=appuser:appgroup src/ /app/src/
COPY --chown=appuser:appgroup alembic.ini /app/

USER appuser

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
