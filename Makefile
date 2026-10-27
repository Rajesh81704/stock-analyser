.PHONY: help install test lint run-api run-backtest fetch-data docker-up docker-down new-strategy clean

PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest

help:
	@echo "AlgoDesk Management Commands:"
	@echo "  make install        Install development dependencies"
	@echo "  make test           Run automated pytest suite"
	@echo "  make lint           Check code with ruff"
	@echo "  make run-api        Start FastAPI dashboard server"
	@echo "  make fetch-data     Download historical 5m candles (--resume)"
	@echo "  make docker-up      Launch PostgreSQL, Redis & AlgoDesk containers"
	@echo "  make docker-down    Stop all Docker containers"
	@echo "  make new-strategy   Scaffold a new strategy: make new-strategy name=my_strat"

install:
	pip install -e .[dev]

test:
	$(PYTEST) tests/ -v

lint:
	ruff check src/ tests/

run-api:
	$(PYTHON) run.py

new-strategy:
	@if [ -z "$(name)" ]; then echo "Error: Specify name, e.g. make new-strategy name=mean_reversion"; exit 1; fi
	$(PYTHON) scripts/create_strategy.py --name $(name)

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
