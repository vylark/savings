# Contributing to vylark/savings

Thank you for your interest in this project!

This repository is maintained as a personal project and portfolio showcase.

### External Contributions
To ensure architectural consistency and preserve unilateral licensing options for future development, **external pull requests and direct code contributions are not being accepted at this time.**

### Feedback & Discussions
* If you encounter a bug or have ideas regarding ledger reconciliation, architecture, or performance, please feel free to open a **GitHub Issue**.
* You are free to fork, experiment with, and study the codebase under the terms of the [MIT License](LICENSE).

---

## Local Development & Testing Guide

If you have forked the repository or are developing locally, please refer to the instructions below for environment setup and project standards.

### 1. Development Setup

#### Prerequisites
* **Python**: `^3.12`
* **uv**: Fast Python package installer (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
* **Docker & Docker Compose**: For running PostgreSQL & Redis services locally
* **Git**

#### Quickstart
1. **Clone the repository**:
   ```bash
   git clone git@github.com:vylark/savings.git
   cd savings
   ```

2. **Create and activate a virtual environment using `uv`**:
   ```bash
   uv venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies using `uv`**:
   ```bash
   uv pip install -r requirements.txt -r requirements-dev.txt
   ```

4. **Set up local environment variables**:
   ```bash
   cp .env.example .env
   ```

5. **Start database and Redis services**:
   ```bash
   docker-compose up -d db redis
   ```

6. **Run Alembic migrations & seed data**:
   ```bash
   alembic upgrade head
   python -m src.db.seed
   ```

7. **Run the API development server**:
   ```bash
   uvicorn src.main:app --reload
   ```

#### Managing & Pinning Dependencies
When adding or updating dependencies:
1. Edit `requirements.in` (for runtime dependencies) or `requirements-dev.in` (for dev dependencies).
2. Compile locked requirements files using `uv`:
   ```bash
   uv pip compile requirements.in -o requirements.txt
   uv pip compile requirements-dev.in -o requirements-dev.txt
   ```

---

### 2. Coding Standards & Conventions

#### Python Documentation
* **Google Style Guide**: All Python documentation, comments, and docstrings must strictly adhere to the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).
* **Mandatory Docstrings**: All modules, classes, public and private methods, and functions must include descriptive docstrings.

#### FastAPI & Async Patterns
* **Asynchronous I/O**: Use `async def` for endpoints and service methods performing database queries or network requests.
* **Rate Limiting**: Always apply `@limiter.limit` decorators from `slowapi` to sensitive, authenticated, or public-facing API endpoints.

---

### 3. Tooling, Linting & Type Checking

#### Formatting & Linting (Ruff)
```bash
ruff format .
ruff check --fix .
```

#### Static Type Checking (Pyright)
```bash
pyright
```

---

### 4. Testing & Database Migrations

#### Running Tests
```bash
pytest
```

#### Database Migrations (Alembic)
When modifying SQLAlchemy models in `src/models/`, generate a new database migration:

```bash
alembic revision --autogenerate -m "descriptive_revision_summary"
```

---

### 5. Commit Messages

All commit messages follow the [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) specification (`<type>(<scope>): <description>`).
