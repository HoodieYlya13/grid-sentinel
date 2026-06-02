.PHONY: help up down restart logs status migrate test clean shell restart-clean

help:
	@echo "SciOps Grid Sentinel - Local Management Console"
	@echo "==============================================="
	@echo "Available commands:"
	@echo "  make up            - Build and launch the docker-compose stack in the background"
	@echo "  make down          - Stop and tear down all containers"
	@echo "  make restart       - Tear down and restart the cluster"
	@echo "  make restart-clean - Clear database volumes, rebuild, and restart clean"
	@echo "  make migrate       - Generate and run database migrations inside the Django container"
	@echo "  make logs          - View and follow output logs of all services"
	@echo "  make status        - Check the running status of the cluster containers"
	@echo "  make test          - Execute Django unit tests inside the control plane"
	@echo "  make shell         - Open a Python Django shell inside the running container"
	@echo "  make clean         - Stop containers and delete all persisted volume database state"

up:
	docker compose up --build -d
	@echo "==============================================="
	@echo "🚀 Cluster stack started successfully!"
	@echo "👉 Open: http://localhost:8000/ to view the dashboard."
	@echo "💡 Run 'make migrate' to initialize the database."
	@echo "==============================================="

down:
	docker compose down

restart: down up

migrate:
	docker compose exec django python manage.py makemigrations nodes
	docker compose exec django python manage.py migrate

logs:
	docker compose logs -f

status:
	docker compose ps

test:
	docker compose exec django python manage.py test

shell:
	docker compose exec django python manage.py shell

clean:
	docker compose down -v
	@echo "🧹 All volumes and database states have been cleaned."

restart-clean:
	docker compose down -v
	docker compose up --build -d
	@echo "Waiting for services to boot..."
	sleep 5
	docker compose exec django python manage.py makemigrations nodes
	docker compose exec django python manage.py migrate
	@echo "✨ Restart clean completed. Open http://localhost:8000/"
