# Stage 1: Build virtual environment
FROM python:3.14-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY requirements.txt requirements-dev.txt ./
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install both prod and dev requirements in build stage
RUN uv pip install -r requirements.txt -r requirements-dev.txt

# Stage 2: Development runtime (hot-reloading, dev dependencies)
FROM python:3.14-slim AS development

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini /app/
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH"

# Development command runs uvicorn with reload
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Stage 3: Production runtime (lightweight, secure, rootless)
FROM python:3.14-slim AS production

WORKDIR /app

# Create non-root system user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -m -s /sbin/nologin appuser

# Only copy runtime dependencies (re-install prod only for final layer)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH"

# Copy source code and change ownership
COPY --chown=appuser:appgroup src/ /app/src/
COPY --chown=appuser:appgroup alembic.ini /app/

USER appuser

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
