.DEFAULT_GOAL := help

UV ?= uv
PYTHON ?=
UV_RUN := $(UV) run$(if $(PYTHON), --python $(PYTHON))
TYPECHECK_PATHS := $(wildcard packages services tests)
PROTO_FILES := $(shell find protos -name '*.proto' 2>/dev/null | sort)
# Верхнеуровневые пакеты pb/ = каталоги protos/ (pyproject.toml в pb/ не трогаем)
GEN_PACKAGES := $(addprefix pb/,$(notdir $(wildcard protos/*)))

.PHONY: help install gen format lint typecheck check test cov smoke up down logs ps stats reset \
	front-install front-lint front-test

help: ## Список целей
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install: ## Установить зависимости всех пакетов workspace
	$(UV) sync --all-packages --all-groups $(if $(PYTHON),--python $(PYTHON))

gen: ## Сгенерировать код из protos/ в pb/
	@if [ -z "$(PROTO_FILES)" ]; then echo "protos/ пуст, генерировать нечего"; exit 0; fi
	rm -rf $(GEN_PACKAGES)
	$(UV_RUN) python -m grpc_tools.protoc -I protos \
		--python_out=pb --grpc_python_out=pb \
		--mypy_out=pb --mypy_grpc_out=pb \
		$(PROTO_FILES)
	find $(GEN_PACKAGES) -type d -exec touch {}/__init__.py \;
	for pkg in $(GEN_PACKAGES); do touch $$pkg/py.typed; done

format: ## ruff format + ruff check --fix
	$(UV_RUN) ruff format .
	$(UV_RUN) ruff check --fix .

lint: ## ruff check
	$(UV_RUN) ruff format --check .
	$(UV_RUN) ruff check .

typecheck: ## mypy strict
	$(UV_RUN) mypy $(TYPECHECK_PATHS)

check: lint typecheck ## lint + typecheck

test: ## Тесты сервисов и stand_core (без smoke)
	$(UV_RUN) pytest

COV_PACKAGES := stand_core catalog_service user_service order_service support_service notification_service gateway

cov: ## Тесты с покрытием stand_core и сервисов
	$(UV_RUN) pytest $(addprefix --cov=,$(COV_PACKAGES)) --cov-report=term-missing:skip-covered --cov-fail-under=80

smoke: ## Smoke-сценарий против поднятого стенда (make up)
	$(UV_RUN) pytest -m stand

up: ## Поднять стенд
	docker compose up -d --build --wait

down: ## Остановить стенд и удалить данные
	docker compose down -v

logs: ## Логи контейнеров
	docker compose logs -f --tail=100

ps: ## Статус контейнеров
	docker compose ps

stats: ## Потребление памяти контейнерами
	docker stats --no-stream

reset: down up ## Пересоздать стенд с чистыми данными

NPM ?= npm

front-install: ## Установить зависимости фронтенда (npm ci)
	$(NPM) ci --prefix frontend

front-lint: ## ESLint + vue-tsc фронтенда
	$(NPM) run lint --prefix frontend

front-test: ## Тесты фронтенда (Vitest)
	$(NPM) run test --prefix frontend
