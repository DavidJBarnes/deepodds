.PHONY: db-up db-down dev-backend dev-frontend dev-worker dev-beat dev migrate migration test lint format

db-up:
	docker compose up -d

db-down:
	docker compose down

dev-backend:
	cd backend && PYTHONPATH=. uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

dev-worker:
	cd backend && PYTHONPATH=. ./run-celery.sh

dev-beat:
	cd backend && PYTHONPATH=. uv run celery -A app.celery_app beat --loglevel=info

dev:
	@echo "Starting all services..."
	$(MAKE) db-up
	$(MAKE) dev-worker &
	$(MAKE) dev-backend &
	$(MAKE) dev-frontend

migrate:
	cd backend && PYTHONPATH=. uv run alembic upgrade head

migration:
	cd backend && PYTHONPATH=. uv run alembic revision --autogenerate -m "$(msg)"

test:
	cd backend && PYTHONPATH=. uv run pytest -v

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

format:
	cd backend && uv run ruff format .

reset-local:
	curl -s -X POST http://localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' -d '{"email":"reset@reset.dev","password":"clear"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" | xargs -I{} curl -s -X POST http://localhost:8000/api/v1/settings/reset-data -H 'Authorization: Bearer {}'

reset-aws:
	curl -s -X POST https://deepodds.davidjbarnes.com/api/v1/auth/register -H 'Content-Type: application/json' -d '{"email":"reset@reset.dev","password":"clear"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" | xargs -I{} curl -s -X POST https://deepodds.davidjbarnes.com/api/v1/settings/reset-data -H 'Authorization: Bearer {}'

reset: reset-local reset-aws
