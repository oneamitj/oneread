.DEFAULT_GOAL := help
PY := .venv/bin/python

help: ## Show this list
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

install: ## Install backend (editable) and frontend deps
	uv pip install -e "backend[dev]"
	cd frontend && npm install

dev-backend: ## Run the API with reload on :8000
	$(PY) -m uvicorn oneread.main:app --reload --host 127.0.0.1 --port 8000

dev-frontend: ## Run Vite on :5173, proxying /api to :8000
	cd frontend && npm run dev

test: ## Run the test suite
	$(PY) -m pytest backend/tests -q

lint: ## Ruff over the backend, tsc over the frontend
	.venv/bin/ruff check backend
	cd frontend && npm run typecheck

build: ## Build the frontend into frontend/dist
	cd frontend && npm run build

serve: build ## Build, then serve everything from :8000
	$(PY) -m uvicorn oneread.main:app --host 127.0.0.1 --port 8000

docker-up: ## Build the image and start it
	docker compose up --build -d

docker-down: ## Stop it
	docker compose down

.PHONY: help install dev-backend dev-frontend test lint build serve docker-up docker-down
