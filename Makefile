.DEFAULT_GOAL := help
PY := .venv/bin/python

help: ## Show this list
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

install: ## Install backend (editable) and frontend deps
	uv pip install -e "backend[dev]"
	cd frontend && npm install

dev-backend: ## Run the API with reload on :8000
	$(PY) -m uvicorn oneread.main:app --reload --host 127.0.0.1 --port 8000 --no-proxy-headers

dev-frontend: ## Run Vite on :5173, proxying /api to :8000
	cd frontend && npm run dev

test: ## Run the test suite
	$(PY) -m pytest backend/tests -q

lint: ## Ruff over the backend, tsc over the frontend
	.venv/bin/ruff check backend
	cd frontend && npm run typecheck

build: ## Build the frontend into frontend/dist
	cd frontend && npm run build

#: How many days the usage table shows. `make stats DAYS=90` for a quarter.
DAYS ?= 30

stats: ## Page views, visitors, signups and sign-ins per day (DAYS=30)
	$(PY) -m oneread.stats --days $(DAYS)

# --no-proxy-headers: uvicorn's default lets a caller on this machine rewrite the
# address its requests appear to come from, and rate limits are keyed on that.
serve: build ## Build, then serve everything from :8000
	$(PY) -m uvicorn oneread.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers

docker-up: ## Build the image and start it
	docker compose up --build -d

docker-down: ## Stop it
	docker compose down

# --- production ---------------------------------------------------------------
# The stack in docker-compose.prod.yml: the app behind nginx, with certbot
# keeping the certificate current. Everything reads .env.prod.
PROD := docker compose -f docker-compose.prod.yml --env-file .env.prod

# ARGS is passed through to the script, so a re-issue is:
#   make prod-init ARGS=--force-cert
prod-init: ## First run: data dir, first certificate, then bring it all up
	./scripts/prod-bootstrap.sh $(ARGS)

prod-update: ## Rebuild and roll forward (this is the deploy)
	$(PROD) up -d --build --remove-orphans
	docker image prune -f

prod-logs: ## Follow the logs
	$(PROD) logs -f --tail=100

prod-ps: ## What's running, and is it healthy
	$(PROD) ps

prod-stats: ## The usage table, read from inside the running container
	$(PROD) exec -T app python -m oneread.stats --days $(DAYS)

prod-restart: ## Restart the app without touching nginx or the certificate
	$(PROD) restart app

prod-down: ## Stop everything (the data and the certificate survive)
	$(PROD) down

prod-cert-renew: ## Renew the certificate now instead of waiting for the timer
	$(PROD) run --rm --entrypoint certbot certbot renew --webroot -w /var/www/certbot --force-renewal
	$(PROD) exec nginx nginx -s reload

prod-nginx-check: ## Parse the nginx config as the running container sees it
	$(PROD) exec nginx nginx -t

# A plain tar of a live SQLite file can catch it mid-write and restore as a
# corrupt database, so the database is snapshotted through SQLite's own online
# backup first and the live files are left out of the archive. Restoring means
# moving backup/oneread.db back up a level — see the README.
prod-backup: ## Snapshot ./data into backups/, database included consistently
	@mkdir -p backups
	$(PROD) exec -T app python -c "import pathlib, sqlite3; \
pathlib.Path('/data/backup').mkdir(exist_ok=True); \
src = sqlite3.connect('file:/data/oneread.db?mode=ro', uri=True); \
dst = sqlite3.connect('/data/backup/oneread.db'); \
src.backup(dst); dst.close(); src.close()"
	tar -czf "backups/oneread-$$(date +%Y%m%d-%H%M%S).tar.gz" \
		--exclude='data/oneread.db' \
		--exclude='data/oneread.db-wal' \
		--exclude='data/oneread.db-shm' \
		data
	$(PROD) exec -T app rm -rf /data/backup
	@ls -lh backups | tail -1

.PHONY: help install dev-backend dev-frontend test lint build stats serve docker-up docker-down \
        prod-init prod-update prod-logs prod-ps prod-stats prod-restart prod-down \
        prod-cert-renew prod-nginx-check prod-backup
