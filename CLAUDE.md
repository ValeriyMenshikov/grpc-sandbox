# CLAUDE.md

Учебный gRPC-стенд маркетплейса. Требования — `docs/stand/grpc-stand-TZ.md`, контракты и коды — `docs/api.md`, принятые решения — `docs/decisions.md` (читать перед изменением поведения; новое решение — новым пунктом туда же).

## Команды

- `make install` — `uv sync` всего workspace (после правки любого `pyproject.toml`)
- `make gen` — после правки `protos/`; `pb/` коммитится, руками не редактируется
- `make check` — ruff format --check + ruff check + mypy strict; `make format` чинит формат
- `make test` — все тесты без smoke; `make cov` — с покрытием (порог 80%)
- `make up` / `make down` / `make reset` — стенд в docker compose (`up` пересобирает образ)
- `make smoke` — smoke против поднятого стенда (маркер `stand`)
- Один сервис: `uv run pytest services/orders`
- Другая версия Python: `UV_PROJECT_ENVIRONMENT=/tmp/stand-venv-314 PYTHON=3.14.2 make install check test` — отдельный venv, `.venv` на 3.12 не трогается; `install` обязателен (без него в venv нет пакетов сервисов). Нужен обычный CPython, не free-threaded `3.14t` (под него нет колёс grpcio-tools)

Перед коммитом: `make check && make test` — зелёные.

## Устройство

- uv workspace: `pb/` (`stand-protos`), `packages/core` (модуль `stand_core`), `services/{users,catalog,orders,support,notifications,gateway}`. Модули сервисов — `user_service`, `catalog_service`, `order_service`, `support_service`, `notification_service`, `gateway`.
- Импорт сгенерированного кода: `from catalog.v1 import catalog_pb2`.
- Каждый gRPC-сервис: `settings.py`, `models.py` (доменные модели, не proto), `repository.py` + `schema.sql`, `convert.py` (домен ↔ proto), `auth.py` (`AUTH_POLICIES`), `handlers/`, `main.py`.
- gateway — не gRPC-сервис: эндпоинты — `routers/<группа>.py` (группа = ресурс: `health`, `users`, `catalog`, `cart`, `orders`), их список — `routers/__init__.py` (`ROUTERS`), корневой роутер — `api.py`, общие query-параметры — `params.py`, gRPC-клиенты к соседям — `clients.py`, JSON-модели ответов — `schemas.py`, маппинг gRPC → HTTP — `errors.py`, contextvars запроса ставит ASGI-middleware `context.py`; `handlers/`, `auth.py` и репозитория нет (docs/decisions.md §16).
- События — RabbitMQ: клиент `stand_core.clients.Rabbit` (topic exchange `stand.events`), тела событий и их разбор — `stand_core.events`. users-service публикует `user.email_confirmation_requested` из `SignUp` (без брокера `SignUp` не падает); notification-service — consumer `EmailConsumer` (фоновая задача в `serve`) → `Mailer` (SMTP в Mailpit) → журнал `notifications.sent_emails`; ошибка — `nack(requeue=False)` в dead-letter, без requeue. Код подтверждения по-прежнему в Redis, письмо — только доставка (docs/decisions.md §28).
- `frontend/` — веб-интерфейс покупателя (Vue 3 + TypeScript + Vite), вне uv workspace; проверки — `make front-lint` / `make front-test` (в `check`/`test` не входят, перед коммитом фронта — тоже зелёные). Код API — `frontend/src/api/`, не `src/lib/` (корневой `.gitignore` игнорирует `lib/`); nginx-прокси `/api` → gateway — `frontend/nginx/default.conf.template` (docs/decisions.md §27).
- Все зависимости — nuke-di `Client` (настройки, Postgres, Redis, репозитории, клиенты к соседям, интерцепторы), внедряются по type hint. Клиент — `@client_dataclass` + `Client`, зависимости — поля (`_postgres: Postgres`; DI смотрит на тип, не на имя, поэтому поля приватные), своё состояние — `field(default=..., init=False)` и заполняется в `connect()`; `__init__` руками не пишем. Исключение — `Settings` и его подклассы: у них явный `__init__(self) -> None` (pydantic, docs/decisions.md §7).

## Хэндлеры

- Один хэндлер на файл: `handlers/<method_snake>_<in>_<out>.py`, где `<in>`/`<out>` — `u` (unary) или `s` (stream): `get_order_u_u.py`, `import_products_s_u.py`, `track_order_u_s.py`, `chat_s_s.py`. Другая версия пакета — префикс: `v2_get_product_u_u.py`, функция `get_product_v2`.
- Каждый новый модуль — в импорт и `__all__` `handlers/__init__.py`, метод — в `auth.py`.
- Сигнатура: `request`, `context: Context` — первые и позиционные, дальше клиенты; все аннотации обязательны. Исходящий стрим — async-генератор с `-> AsyncIterator[Resp]`.

```python
@rpc("GetOrder", package="orders.v1", service="OrderService")
async def get_order(
    request: orders_pb2.GetOrderRequest,
    context: Context,
    repository: OrderRepository,
) -> orders_pb2.GetOrderResponse:
```

- Ошибки — только доменные исключения `stand_core.grpc` (`InvalidArgument([FieldViolation(...)])`, `NotFound("order", id)`, `FailedPrecondition([PreconditionViolation(type, subject, description)])`, ...). `context.abort` не вызывать — исключение `LegacyResetPassword` (намеренный антипример).
- Текущий пользователь, `request_id`, `authorization`, deadline — из contextvars, их ставят интерцепторы; хэндлер metadata сам не разбирает (кроме своих ключей, через `metadata_value`).

## Шаблон main.py

```python
"""Точка входа <name>-service: `python -m <name>_service.main`."""

from nuke_di import DI, Shutdown, worker
from stand_core.grpc import (
    GRPC_HANDLERS,
    grpc_server,
    inject_handlers,
    register_auth_policies,
    resolve_interceptors,
)
from stand_core.logging import configure_logging

import <name>_service.handlers  # noqa: F401  — регистрирует хэндлеры
from <name>_service.auth import AUTH_POLICIES
from <name>_service.settings import <Name>Settings

configure_logging(DI.resolve(<Name>Settings).log_level)
register_auth_policies(AUTH_POLICIES)
HANDLERS = inject_handlers(GRPC_HANDLERS)  # DI.inject каждого хэндлера, до connect()
INTERCEPTORS = resolve_interceptors()  # DI.resolve каждого интерцептора (они — Client)


@worker
async def serve(shutdown: Shutdown) -> None:
    async with grpc_server(HANDLERS, INTERCEPTORS):
        await shutdown.wait()
```

Фоновые задачи (как доставка в order-service и consumer писем в notification-service) запускаются внутри `serve` через `BackgroundTasks` nuke-di. gateway — исключение: `uvicorn.run`, а не `@worker` (docs/decisions.md §16).

## Соглашения

- Python ≥ 3.12, mypy strict, ruff (строка 100). `type: ignore` вне `pb/` — нельзя (единственное обоснованное исключение — `packages/core/tests/test_rpc.py`).
- Комментарии, докстринги, docs — на русском; сообщения ошибок gRPC — на английском.
- Новая переменная окружения — в `.env.example`, `docker-compose.yml` (с дефолтом `${VAR:-...}`) и `Settings` сервиса.
- Порт внутри контейнера (`GRPC_PORT`, у gateway `HTTP_PORT`) задаётся в compose литералом и в `.env.example` не выносится; порт на хосте меняется через `<NAME>_PORT`.
- Тесты: хэндлеры напрямую с фейками (`tests/fakes.py`) и `Mock`-контекстом; `test_server.py` — сервис in-process со всеми интерцепторами, подмена клиентов через `DI.override`; `test_wiring.py` — дерево клиентов из настоящего `main.py`; тесты против Postgres/Redis из compose пропускаются, если их нет. Rich details в тестах — `stand_core.testing.rich_status`.
- Коммиты: `feat: ...` / `fix: ...` / `docs: ...`.
