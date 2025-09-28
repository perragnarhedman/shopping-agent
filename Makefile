.PHONY: help build up down dev logs clean status

help:
	@echo "Shopping Agent Docker Management"; \
	echo "Commands:"; \
	echo "  make build   - Build images"; \
	echo "  make up      - Start containers"; \
	echo "  make down    - Stop containers"; \
	echo "  make logs    - Tail logs"; \
	echo "  make clean   - Remove containers and volumes"; \
	echo "  make status  - Show status";

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f shopping-agent

clean:
	docker compose down -v || true
	docker system prune -f || true

status:
	docker compose ps


