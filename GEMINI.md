# Workspace Rules & Guidelines

This document outlines the coding standards, conventions, and rules for this project. All contributors (including AI agents) must strictly adhere to these guidelines.

## 1. Commit Messages
All commit messages must follow the **Conventional Commits 1.0.0** specification.
*   Format: `<type>(<scope>): <description>` (scope is optional).
*   Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
*   Example: `feat(auth): add user registration endpoint`

## 2. Python Documentation Standards
*   **Google Style Guide**: All Python documentation, comments, and docstrings must strictly follow the [Google Python Style Guide (Section 3.8)](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).
*   **Mandatory Docstrings**: All Python modules, classes, public/private methods, and functions must have a descriptive docstring.
*   **Additional Comments**: Consider adding additional inline documentation in Python files beyond standard class/function docstrings, but do so **sparingly** and only when it adds clear, meaningful value to readability and long-term maintainability.

## 3. Tooling & Linting Integration (Ruff, Pyright, Alembic, Pytest)
*   **Formatting & Linting**: Always format the code using `ruff format` and lint using `ruff check --fix` on modified Python files.
*   **Type Safety**: Ensure type safety and valid annotations by running type checks (using Pyright) on modified Python files.
*   **Database Migrations**: When database models are modified, always generate a database migration via Alembic: `alembic revision --autogenerate -m "revision_description"`. Do not write migrations manually unless custom data migrations are required.
*   **Regression Testing**: Every bug fix or new feature must have corresponding tests added under `tests/`. Run `pytest` to verify all tests pass and coverage is maintained before finalizing the work.

## 4. FastAPI & Async Conventions
*   **Asynchronous I/O**: Use `async def` for endpoints and service methods performing database queries or network requests.
*   **Rate Limiting**: Always apply slowapi `@limiter.limit` decorators to sensitive, authenticated, or public-facing API endpoints to prevent abuse.

## 5. PR Code Reviews & GH CLI Guidelines
* **Mandatory Use of GH CLI**: When requested to perform a code review on a Pull Request, always execute the review using the GitHub CLI (`gh pr view`, `gh pr diff`, `gh pr review`).
* **Context & History Awareness**: Prior to performing a code review, always fetch and analyze previous comments and review history on the PR (`gh pr view <PR> --json reviews,comments`) to prevent regressions or conflicting recommendations.
* **Self-Authored PR Restrictions**: GitHub API does not permit requesting changes or approving PRs authored by the authenticated user account. When reviewing a PR owned by the current user, submit the review using `--comment` instead of `--request-changes` or `--approve`.


