# ============================================================================
# AWS Cloud Workflow Orchestrator - Developer Automation Makefile
# ============================================================================

.PHONY: help setup test test-cov lint format clean docker-up docker-down docker-logs dashboard-install dashboard-dev dashboard-build

PYTHON ?= python
PIP ?= pip

help:
	@echo "AWS Cloud-Native Workflow Orchestrator Development Commands:"
	@echo "  make setup             - Install production and development dependencies"
	@echo "  make test              - Run test suite"
	@echo "  make test-cov          - Run tests with terminal coverage report"
	@echo "  make lint              - Check code quality with ruff"
	@echo "  make format            - Auto-format code with ruff"
	@echo "  make clean             - Remove Python bytecode, cache, and build artifacts"
	@echo "  make docker-up         - Start LocalStack and all backend services via Docker"
	@echo "  make docker-down       - Stop all running Docker containers"
	@echo "  make docker-logs       - Stream logs from Docker services"
	@echo "  make dashboard-install - Install React Admin Dashboard dependencies"
	@echo "  make dashboard-dev     - Start Vite frontend dev server on port 3000"
	@echo "  make dashboard-build   - Build production static bundle for dashboard"

setup:
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/

test-cov:
	$(PYTHON) -m pytest --cov=src --cov-report=term-missing tests/

lint:
	$(PYTHON) -m ruff check src/ tests/

format:
	$(PYTHON) -m ruff format src/ tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.py[cod]" -delete
	rm -rf .pytest_cache .coverage htmlcov/ build/ dist/ *.egg-info

docker-up:
	docker compose -f docker/docker-compose.yml up -d --build

docker-down:
	docker compose -f docker/docker-compose.yml down

docker-logs:
	docker compose -f docker/docker-compose.yml logs -f

dashboard-install:
	cd dashboard && npm install

dashboard-dev:
	cd dashboard && npm run dev

dashboard-build:
	cd dashboard && npm run build
