.PHONY: help up down test lint demo

help:
	@echo "Targets:"
	@echo "  up    docker compose up -d"
	@echo "  down  docker compose down"
	@echo "  test  uv run pytest -q tests/spec tests/unit"
	@echo "  lint  uv run ruff check ."
	@echo "  demo  kill switch evidence run -> evidence/killswitch_demo.txt"

up:
	docker compose up -d

down:
	docker compose down

test:
	uv run pytest -q tests/spec tests/unit

lint:
	uv run ruff check .

demo:
	uv run python -m scripts.killswitch_demo | tee evidence/killswitch_demo.txt
