# Developer Contribution Guide

## Workflow
1. Create a development virtual environment (`python -m venv .venv`).
2. Install project requirements (`pip install -r requirements.txt -r requirements-dev.txt`).
3. Run code formatting and linting: `ruff check .` and `ruff format --check .`.
4. Verify security compliance: `bandit -r src -ll`.
5. Run the test suite: `pytest --cov=src`.

## Submitting Pull Requests
- Branch naming convention: `feature/*` or `fix/*`.
- Ensure all test assertions and quality gates pass prior to opening PRs.
