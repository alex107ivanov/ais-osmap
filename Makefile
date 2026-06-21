PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
DOCKER_COMPOSE ?= docker compose

.PHONY: venv install install-dev run test clean docker-up docker-down

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(PIP) install -r requirements.txt

install-dev: venv
	$(PIP) install -r requirements-dev.txt

run:
	$(PYTHON) ais_map.py

test:
	$(PYTEST) -q

docker-up:
	mkdir -p data
	$(DOCKER_COMPOSE) up --build

docker-down:
	$(DOCKER_COMPOSE) down

clean:
	rm -rf __pycache__ .pytest_cache htmlcov
