# ТЗ: учебный стенд для курса «gRPC API Test Automation (Python)»

## 0. Как читать это ТЗ

Ты — агент-разработчик. Задача — написать с нуля **учебный стенд**: упрощённый бэкенд маркетплейса из нескольких gRPC-сервисов, который поднимается одной командой в docker compose. Против этого стенда студенты курса будут писать автотесты на Python.

Стенд — это **не** фреймворк автотестов. В репозитории нет тестов курса, только сами сервисы и их собственные тесты.

Приоритеты при конфликте требований:
1. Легковесность и простота запуска на любом ноутбуке.
2. Правдоподобие: каждый метод должен отвечать на вопрос «кто и зачем вызывает это в настоящем маркетплейсе». Методов «для галочки», чтобы показать тип вызова, быть не должно.
3. Учебная ценность: поведение сервисов даёт материал для тестов (раздел 6).
4. Чистота кода: стенд будут читать студенты.

Если что-то в ТЗ неоднозначно, выбери самое простое решение, которое выполняет требование, и запиши его в `docs/decisions.md`.

---

## 1. Контекст

- Курс учит писать автотесты для gRPC API на Python: unary-вызовы, все виды стримов, интерцепторы, статус-коды и rich error model, metadata, deadline, моки соседних сервисов, CI.
- Главная мысль курса: **gRPC — протокол для связи сервисов между собой, а не для браузера**. Поэтому стенд — это несколько сервисов, которые вызывают друг друга по gRPC. Снаружи у него только REST-шлюз (BFF) для «фронта».
- Автотест в курсе ведёт себя как ещё один сервис внутри контура: ходит в сервисы напрямую по gRPC, а для проверок состояния — в Postgres и Redis, письма — через REST API Mailpit.

---

## 2. Жёсткие ограничения

| # | Ограничение |
|---|---|
| C1 | Только Python, **3.12+**: `requires-python = ">=3.12"`, ruff `target-version = "py312"`, mypy `python_version = "3.12"`. Не использовать возможности новее 3.12. Стенд должен запускаться на 3.12, 3.13 и 3.14. |
| C2 | Инфраструктура — **только Postgres, Redis, RabbitMQ и Mailpit**. Ничего сверх этого списка: никаких Kafka, ZooKeeper, NATS, Envoy, Prometheus и т.п. RabbitMQ — шина доменных событий (запрос письма с кодом, смена статуса заказа), Mailpit — локальный почтовый ящик, наружу почта не уходит (docs/decisions.md §28, §29). |
| C3 | Весь стенд в покое укладывается примерно в **1 ГБ RAM** (замер `docker stats` после `make up` и прогона smoke-сценария, результат — в README). |
| C4 | DI — только **[nuke-di](https://github.com/troyan-dy/nuke-di)** (PyPI `nuke-di`, v2.x). Никаких других DI-контейнеров. |
| C5 | gRPC-хэндлеры — свободные async-функции с декоратором **`rpc(method_name, package, service)`** по образцу фреймворка Nuke (раздел 5). Декоратор и сервер реализуем сами в `stand_core`. |
| C6 | Зависимости — **uv** (workspace). Линтер и форматтер — **ruff**, типизация — **mypy** strict (с плагином nuke-di). |
| C7 | Все действия — через **Makefile**. |
| C8 | Сервер — **grpc.aio**. Синхронный gRPC-сервер не использовать. |
| C9 | Конфигурация — только через переменные окружения (`.env`), никаких захардкоженных адресов. |

---

## 3. Предметная область и архитектура

Маркетплейс: покупатель регистрируется, ищет товары, кладёт их в корзину, оформляет заказ, следит за доставкой и пишет в поддержку. Продавец загружает и выгружает свой каталог.

```
Браузер ──HTTP──> frontend (nginx) ──/api──> gateway (BFF) ──gRPC──> user-service ──────────> Postgres, Redis
                                                           ├─gRPC──> catalog-service ─────────> Postgres
                                                           └─gRPC──> order-service ──gRPC──> catalog-service (StockService)
                                                                          ├─gRPC──> user-service (GetMe: email для снимка)
                                                                          └──> Postgres, Redis
               приложение поддержки ──gRPC──> support-service ──gRPC──> order-service
                                                    └──> Postgres
frontend (nginx) ──/mail──> Mailpit (веб-ящик + REST API)
user-service  ──publish user.email_confirmation_requested──┐
order-service ──publish order.status_changed──────────────┤
                                                           v
                RabbitMQ (stand.events) ──┬──> notification-service ──SMTP──> Mailpit
                                          │          └──> Postgres (журнал писем)
                                          └──> support-service ──> Postgres (проекция статусов заказа)
Автотесты курса ──gRPC──> любой сервис;  ──SQL/Redis──> проверки состояния;  ──HTTP──> Mailpit API
```

| Компонент | Порт (хост) | Протокол | За что отвечает |
|---|---|---|---|
| frontend | 3000 | HTTP (nginx) | Веб-интерфейс покупателя (Vue 3), прокси `/api` → gateway (docs/decisions.md §27). |
| gateway | 8080 | REST (FastAPI) → gRPC | BFF для веб-фронта. |
| user-service | 50051 | gRPC | Регистрация, подтверждение email, вход, профиль. |
| catalog-service | 50052 | gRPC | Каталог и поиск; импорт/экспорт товаров продавца; остатки и резервы (внутренний `StockService`). |
| order-service | 50053 | gRPC | Корзина, оформление заказа, заказы, отслеживание доставки. |
| support-service | 50054 | gRPC + consumer | Чат покупателя с поддержкой по заказу; проекция статусов заказа из событий RabbitMQ (`GetOrderTimeline`). |
| notification-service | 50055 | gRPC + consumer | Забирает события из RabbitMQ (код подтверждения, доставка заказа), отправляет письма по SMTP в Mailpit, журнал попыток (`ListNotifications`). |
| postgres | 5432 | SQL | Одна БД `stand`, схема на сервис: `users`, `catalog`, `orders`, `support`, `notifications`. |
| redis | 6379 | RESP | Коды подтверждения, сессии, корзины, ключи идемпотентности, pub/sub статусов заказов. |
| rabbitmq | 5672 | AMQP | Шина событий: topic exchange `stand.events`, у каждого потребителя своя очередь и dead-letter. Без management-плагина. |
| mailpit | 1025 / 8025 | SMTP / HTTP | Локальный почтовый сервер: веб-ящик `/mail/` и REST API для тестов. |

Типы вызовов и зачем они в маркетплейсе:

| Тип | Метод | Кто вызывает и зачем |
|---|---|---|
| unary | почти все методы | Обычные запрос-ответ. |
| client stream | `catalog.v1.CatalogService/ImportProducts` | Продавец (или его ERP) загружает фид на тысячи товаров. Одно сообщение на все строки упрётся в лимит размера, поэтому строки идут потоком, а в ответ приходит отчёт об импорте. |
| server stream | `catalog.v1.CatalogService/ExportProducts` | Продавец выгружает свой каталог в ERP — тысячи позиций без пагинации и без огромного ответа. |
| server stream | `orders.v1.OrderService/TrackOrder` | Мобильное приложение и BFF показывают статус доставки в реальном времени, без опроса. |
| bidi | `support.v1.SupportService/Chat` | Чат с поддержкой: покупатель пишет когда хочет, поддержка тоже отвечает когда хочет. Потоки независимы: сервер может прислать сообщение, не дождавшись клиента. |

Стримы работают **без брокеров**: `TrackOrder` получает изменения статуса через Redis pub/sub (так работало бы и при нескольких репликах order-service), чат — внутри процесса support-service. RabbitMQ — для доменных событий с независимыми подписчиками: `user.email_confirmation_requested` (письмо с кодом) и `order.status_changed` — одно событие, две очереди: письмо о доставке в notification-service и проекция статусов в support-service (fan-out, docs/decisions.md §29). Redis pub/sub — эфемерный канал для живого клиента, RabbitMQ — события, которые переживают остановку потребителя.

---

## 4. Структура репозитория

```
grpc-stand/
├── Makefile
├── pyproject.toml              # uv workspace, общие настройки ruff/mypy/pytest
├── uv.lock
├── .env.example
├── docker-compose.yml
├── docker/
│   └── Dockerfile              # ОДИН базовый образ для всех Python-сервисов
├── protos/
│   ├── common/v1/money.proto   # Money, Pagination — общие типы
│   ├── users/v1/users.proto
│   ├── catalog/v1/catalog.proto      # CatalogService + StockService
│   ├── catalog/v2/catalog.proto      # CatalogService v2 (раздел 6.3)
│   ├── orders/v1/orders.proto
│   ├── support/v1/support.proto
│   └── notifications/v1/notifications.proto  # журнал писем (ListNotifications)
├── packages/
│   └── core/                   # общая библиотека
│       └── src/stand_core/
│           ├── settings.py     # Settings как nuke-di Client (pydantic-settings)
│           ├── clients/        # Postgres (asyncpg), Redis (redis.asyncio), Rabbit (aio-pika), базовый gRPC-клиент к соседям
│           ├── events.py       # события шины: routing key, тело, разбор с валидацией
│           ├── grpc/
│           │   ├── rpc.py          # декоратор rpc, GRPC_HANDLERS, сверка с дескрипторами
│           │   ├── server.py       # grpc_server(): generic handlers, reflection, health, graceful stop
│           │   ├── di.py           # inject_handlers(), resolve_interceptors()
│           │   ├── interceptors/   # request_id, logging, auth, stream_count, exception_handling
│           │   ├── errors.py       # доменные исключения → статус-коды + rich details
│           │   └── context.py      # Context, contextvars: request_id, текущий пользователь
│           └── logging.py      # structlog, JSON
├── services/
│   ├── users/    {src/user_service/{handlers/,repository.py,schema.sql,main.py}, tests/}
│   ├── catalog/  {...}
│   ├── orders/   {...}
│   ├── support/  {...}
│   ├── notifications/  {src/notification_service/{consumer.py,mailer.py,templates.py,handlers/,...}, tests/}
│   └── gateway/  {src/gateway/{routers/,api.py,main.py}, tests/}
├── pb/                         # сгенерированный код (в git — да; ruff/mypy его исключают)
├── frontend/                   # веб-интерфейс покупателя: Vue 3 + Vite, nginx-прокси /api → gateway, /mail → Mailpit
│   ├── src/{api,composables,components,pages}/
│   ├── nginx/default.conf.template
│   └── Dockerfile              # node:22-alpine (сборка) → nginx:alpine
└── docs/
    ├── decisions.md
    └── api.md                  # методы, статус-коды, metadata (раздел 6)
```

Принцип расширяемости: **новый сервис = папка `services/<name>` + контракт `protos/<name>/v1` + блок в `docker-compose.yml`**. Базовый образ, настройки, клиенты к Postgres/Redis, декоратор `rpc` и сборка сервера берутся из `stand_core` без копипасты.

---

## 5. Декоратор `rpc` и gRPC-сервер

Повторяем подход внутреннего фреймворка Nuke (`nuke/applications/grpc.py`). Ниже его API, перенесённый в `stand_core`, и что мы делаем лучше оригинала. Хэндлер — **свободная async-функция**, а не метод servicer-класса. Сквозная логика (ошибки, логи, авторизация, request-id) живёт в **серверных интерцепторах**, а не в декораторе.

### 5.1. Декоратор и реестр (как в Nuke)

```python
# stand_core/grpc/rpc.py
class GrpcTypeEnum(str, Enum):
    stream_stream = "stream_stream"
    stream_unary = "stream_unary"
    unary_stream = "unary_stream"
    unary_unary = "unary_unary"

IN_OUT_METHOD_TYPE = {(True, True): stream_stream, (True, False): stream_unary,
                      (False, True): unary_stream, (False, False): unary_unary}
METHOD_MAP = {stream_stream: grpc.stream_stream_rpc_method_handler, ...}  # по типу вызова

@dataclass(frozen=True)
class MethodSignature:
    name: str       # "ImportProducts"
    service: str    # "CatalogService"
    package: str    # "catalog.v1"

@dataclass
class MethodAnnotation:
    request: type[Message]
    response: type[Message]
    method: Callable
    grpc_type: GrpcTypeEnum

GRPC_HANDLERS: dict[MethodSignature, MethodAnnotation] = {}

def rpc(method_name: str, package: str, service: str) -> Callable: ...
```

Правила `rpc` (как в Nuke):
- Сигнатура хэндлера: **первый аргумент `request`, второй `context`**, оба с type hints, плюс аннотация возврата. Иначе — `ValueError` при импорте модуля.
- Тип вызова и классы сообщений берутся из type hints (`get_type_hints`):
  - `request: AsyncIterator[Req]` — входящий стрим, иначе unary;
  - `-> AsyncIterator[Resp]` — исходящий стрим (хэндлер — async-генератор), иначе unary.
- Декоратор только регистрирует хэндлер в `GRPC_HANDLERS` и возвращает функцию без изменений, поэтому её можно вызвать в юнит-тесте напрямую.
- Остальные параметры после `context` — nuke-di клиенты, их внедряет контейнер (5.3).
- `Context` — алиас `grpc.aio.ServicerContext`, экспортируется из `stand_core`.

Пример, все 4 типа вызовов:

```python
from typing import AsyncIterator
from stand_core import Context, rpc
from catalog.v1 import catalog_pb2
from support.v1 import support_pb2


@rpc("GetProduct", package="catalog.v1", service="CatalogService")  # unary
async def get_product(
    request: catalog_pb2.GetProductRequest, context: Context, products: ProductRepository
) -> catalog_pb2.Product: ...


@rpc("ImportProducts", package="catalog.v1", service="CatalogService")  # client stream
async def import_products(
    request: AsyncIterator[catalog_pb2.ImportProductsRequest],
    context: Context,
    products: ProductRepository,
) -> catalog_pb2.ImportReport: ...


@rpc("ExportProducts", package="catalog.v1", service="CatalogService")  # server stream
async def export_products(
    request: catalog_pb2.ExportProductsRequest, context: Context, products: ProductRepository
) -> AsyncIterator[catalog_pb2.Product]:
    async for product in products.iter_by_seller(current_user().id):
        if context.done():
            break
        yield product


@rpc("Chat", package="support.v1", service="SupportService")  # bidi
async def chat(
    request: AsyncIterator[support_pb2.ChatRequest],
    context: Context,
    chats: ChatHub,
    orders: OrdersClient,
) -> AsyncIterator[support_pb2.ChatEvent]: ...
```

Один хэндлер — один файл в `services/<name>/src/<pkg>/handlers/`. Имя файла — snake_case от имени метода с суффиксом типа вызова, как в Nuke: `get_product_u_u.py`, `import_products_s_u.py`, `export_products_u_s.py`, `chat_s_s.py`. `handlers/__init__.py` импортирует все хэндлеры, и это регистрирует их.

### 5.2. Сервер (как в Nuke, с улучшениями)

`stand_core/grpc/server.py` — `grpc_server(grpc_handlers, interceptors)`, async context manager, как в Nuke:
1. `grpc.aio.server(interceptors=..., options=...)` с keepalive-опциями из Nuke: `min_ping_interval_without_data_ms=1000`, `max_ping_strikes=3`, `keepalive_permit_without_calls=1`, `keepalive_time_ms=20000`.
2. Группирует хэндлеры по `f"{package}.{service}"`, строит `METHOD_MAP[grpc_type](method, request_deserializer=request.FromString, response_serializer=response.SerializeToString)`, затем `grpc.method_handlers_generic_handler` на каждый сервис и `server.add_generic_rpc_handlers(...)`.
3. Server reflection по именам зарегистрированных сервисов + `reflection.SERVICE_NAME`. Модули `_pb2` всех сервисов процесса должны быть импортированы: дескрипторы берутся из пула по умолчанию.
4. Порт — из env `GRPC_PORT`.

Улучшения относительно Nuke (обязательны):
- **Сверка с proto при старте.** Для каждого `MethodSignature` найти метод в пуле дескрипторов и проверить:
  - метод существует;
  - `client_streaming` / `server_streaming` совпадают с `grpc_type`;
  - `request` / `response` совпадают с `input_type` / `output_type`.

  Расхождение — понятная ошибка до `server.start()`. Методы сервиса без хэндлера дают warning при старте и отвечают `UNIMPLEMENTED`.
- **Health service** (`grpcio-health-checking`): статус `SERVING` по каждому сервису после старта — для healthcheck в compose.
- **Graceful stop**: `await server.stop(grace)` с `grace < SHUTDOWN_GRACE_SECONDS`, а в `finally` — `await server.stop(None)`. В Nuke сразу `stop(None)`.

### 5.3. Связка с nuke-di

В Nuke хэндлеры внедряются через `DI.inject` в lifespan приложения (`inject_handler`, уже обёрнутые `functools.partial` пропускаются), до `async with DI`. В стенде сервис запускается через `@worker` nuke-di ([Servers inside a worker → grpc.aio](https://github.com/troyan-dy/nuke-di/blob/master/docs/guide/servers-in-workers.md#grpcaio)).

Важно: `@worker` запускает процесс **в момент декорирования**, если модуль — `__main__` ([ADR-0002](https://github.com/troyan-dy/nuke-di/blob/master/docs/adr/0002-entrypoint-runs-on-decoration.md)). Поэтому хэндлеры и интерцепторы внедряются **на уровне модуля, до** объявления worker'а, а worker — последний в файле:

```python
# services/catalog/src/catalog_service/main.py
from nuke_di import Shutdown, worker
from stand_core.grpc import GRPC_HANDLERS, grpc_server, inject_handlers, resolve_interceptors

import catalog_service.handlers  # noqa: F401  — регистрирует хэндлеры

HANDLERS = inject_handlers(GRPC_HANDLERS)  # DI.inject каждого хэндлера, до connect()
INTERCEPTORS = resolve_interceptors()  # DI.resolve каждого интерцептора (они — Client)


@worker
async def serve(shutdown: Shutdown) -> None:
    async with grpc_server(HANDLERS, INTERCEPTORS):
        await shutdown.wait()
```

`GRPC_HANDLERS` — глобальный реестр, как в Nuke. В процесс сервиса импортируются только его хэндлеры. Тест wiring'а (раздел 9) проверяет, что дерево клиентов каждого сервиса собирается.

### 5.4. Серверные интерцепторы

Как в Nuke, каждый интерцептор — `grpc.aio.ServerInterceptor` и одновременно nuke-di `Client`: берёт зависимости по type hints и резолвится через DI. Порядок выполнения:

| # | Интерцептор | Что делает |
|---|---|---|
| 1 | `RequestIdInterceptor` | Берёт `x-request-id` из metadata или генерирует uuid, кладёт в contextvar, отдаёт клиенту в initial metadata. |
| 2 | `LoggingInterceptor` | Одна JSON-строка на вызов (structlog): метод, тип вызова, `request_id`, статус, длительность; для стримов — число сообщений. Пароли, токены и коды маскируются. |
| 3 | `AuthInterceptor` | Политика по полному имени метода из таблицы в коде сервиса (раздел 6.0). |
| 4 | `StreamCountInterceptor` | Для server-stream и bidi выставляет trailing metadata `x-items-count`. |
| 5 | `ExceptionHandlingInterceptor` | Доменные исключения → статус + rich details (таблица ниже); любое другое → `INTERNAL`, стек только в лог. |

| Исключение (`stand_core.grpc.errors`) | Статус | Details (`google.rpc`, через `grpcio-status`) |
|---|---|---|
| `InvalidArgument(field_violations)` | `INVALID_ARGUMENT` | `BadRequest` |
| `NotFound` | `NOT_FOUND` | `ResourceInfo` |
| `AlreadyExists` | `ALREADY_EXISTS` | `ResourceInfo` |
| `Unauthenticated` | `UNAUTHENTICATED` | — |
| `PermissionDenied` | `PERMISSION_DENIED` | `ErrorInfo` (reason, например `SELLER_ROLE_REQUIRED`) |
| `FailedPrecondition` | `FAILED_PRECONDITION` | `PreconditionFailure` |
| `ResourceExhausted` | `RESOURCE_EXHAUSTED` | `QuotaFailure` |
| `DependencyUnavailable` | `UNAVAILABLE` | `ErrorInfo` (reason, сосед) |
| прочее | `INTERNAL` | — |

Отдельный случай — антипример `LegacyResetPassword` (6.1): он сам делает `context.abort(StatusCode.UNKNOWN, "Validation failed")`.

Если обернуть стримы в интерцепторе grpc.aio слишком сложно (интерцептор видит `RpcMethodHandler`, а не поток), допускается сделать пп. 4–5 обёрткой хэндлера при сборке в `grpc_server`. Решение записать в `docs/decisions.md`. Публичный API `rpc` при этом не меняется.

Deadline: хэндлер видит оставшееся время через `context.time_remaining()`, исходящие вызовы к соседям передают его дальше (5.5).

### 5.5. Клиенты (nuke-di `Client`)

- Каждая зависимость — подкласс `nuke_di.Client`: I/O только в `connect()` / `disconnect()`, в `__init__` — только зависимости. См. [Clients guide](https://github.com/troyan-dy/nuke-di/blob/master/docs/guide/clients.md).
- `Settings(Client)` — pydantic-settings, читает env.
- `Postgres(Client)` — пул asyncpg. Каждый сервис при старте применяет свой идемпотентный `schema.sql` (`CREATE SCHEMA/TABLE IF NOT EXISTS`) и сиды. Alembic не нужен.
- `Redis(Client)` — redis.asyncio.
- Клиенты к соседям — общий базовый класс в `stand_core.clients`: канал grpc.aio + типизированные методы. Обязательно:
  - дефолтный deadline;
  - проброс `x-request-id`, оставшегося deadline и (где нужно) `authorization` пользователя;
  - `UNAVAILABLE` / `DEADLINE_EXCEEDED` соседа → `DependencyUnavailable`;
  - адрес соседа из env (`CATALOG_ADDR`, `ORDERS_ADDR`) — так курс подменяет соседа моком.

  Конкретные клиенты: `StockClient` в order-service, `OrdersClient` в support-service.

---

## 6. Контракты и поведение

Пакеты proto: `common.v1`, `users.v1`, `catalog.v1`, `catalog.v2`, `orders.v1`, `support.v1`. Деньги — `common.v1.Money` (`units`, `nanos`, `currency_code`), даты — `google.protobuf.Timestamp`, статусы — enum, `optional` — там, где важно отличать «не задано» от нуля. Списки с пагинацией — `page_size` + `page_token` / `next_page_token`. Полную таблицу методов, статус-кодов и metadata — в `docs/api.md`.

### 6.0. Авторизация (как в настоящем контуре)

- `x-api-key` — ключ **сервиса-клиента** внутри контура, обязателен на всех методах (кроме reflection и health). Неверный или отсутствует → `UNAUTHENTICATED`. Автотесты, gateway и сервисы шлют его всегда.
- `authorization: Bearer <access_token>` — токен **пользователя**, нужен на методах от имени пользователя (колонка Auth = `user`). Токен ищется в Redis `session:{token}`, пользователь и его роль кладутся в contextvar. Нет или истёк → `UNAUTHENTICATED`.
- Роли: `BUYER`, `SELLER`. Методы продавца (Auth = `seller`) для покупателя → `PERMISSION_DENIED` + `ErrorInfo(reason="SELLER_ROLE_REQUIRED")`.
- Внутренние методы (Auth = `service`) — только `x-api-key`, без пользователя: это вызовы сервис → сервис.

### 6.1. users.v1 — `UserService` (порт 50051)

| Метод | Auth | Поведение и ошибки |
|---|---|---|
| `SignUp` | service | `email`, `password`, `display_name`, `role` (по умолчанию `BUYER`). Создаёт пользователя в статусе `PENDING`. 6-значный код подтверждения — в Redis `confirm:{email}`, TTL 15 мин; код уходит письмом: событие `user.email_confirmation_requested` в RabbitMQ → notification-service → Mailpit (автотест берёт письмо из REST API Mailpit). Недоступный брокер регистрацию не ломает: ошибка публикации логируется, письма нет, код в Redis есть. Ошибки: `INVALID_ARGUMENT` + `BadRequest` (невалидный email, пароль < 8 символов, пустое имя), `ALREADY_EXISTS`. |
| `ConfirmEmail` | service | `email`, `code`. Код неверный → `INVALID_ARGUMENT`; истёк или не найден → `NOT_FOUND`; уже подтверждён → `FAILED_PRECONDITION`. |
| `SignIn` | service | Возвращает `access_token` (Redis, TTL — env `SESSION_TTL_S`, по умолчанию 3600) и `expires_at`. Неверная пара → `UNAUTHENTICATED`; email не подтверждён → `FAILED_PRECONDITION`. |
| `SignOut` | user | Удаляет сессию. |
| `GetMe` | user | Профиль текущего пользователя. |
| `UpdateProfile` | user | Частичное обновление через `google.protobuf.FieldMask` (`display_name`, `phone`). Неизвестный путь в маске → `INVALID_ARGUMENT`. |
| `LegacyResetPassword` | service | **Намеренный антипример**: на любую ошибку валидации отдаёт `UNKNOWN` с текстом `Validation failed` без details. Пометить комментарием в коде и в `docs/api.md`. |

Сиды: продавец `seller@stand.local`, пароль из env `SEED_SELLER_PASSWORD`, подтверждён.

### 6.2. catalog.v1 — `CatalogService` и `StockService` (порт 50052)

`CatalogService`:

| Метод | Тип | Auth | Поведение |
|---|---|---|---|
| `GetProduct` | unary | service | По `product_id`. `NOT_FOUND`. |
| `SearchProducts` | unary | service | Текст, категория, диапазон цены, сортировка; пагинация `page_token`. Невалидный `page_token` → `INVALID_ARGUMENT`. |
| `ImportProducts` | client stream | seller | Первое сообщение — заголовок импорта (`mode: UPSERT / CREATE_ONLY`), дальше строки (`offer_id`, `name`, `category`, `price`, `stock`). Ответ — `ImportReport`: `created`, `updated`, `failed` и список ошибок по строкам (номер строки, поле, описание). Импорт **не падает целиком** из-за плохой строки. Стрим без заголовка → `INVALID_ARGUMENT`. Больше `IMPORT_MAX_ROWS` строк (по умолчанию 10 000) → `RESOURCE_EXHAUSTED` + `QuotaFailure`. |
| `ExportProducts` | server stream | seller | Все товары текущего продавца, по одному; фильтр `updated_since` (Timestamp). Trailing metadata `x-items-count`. |

`StockService` — внутренний, вызывает order-service:

| Метод | Тип | Auth | Поведение |
|---|---|---|---|
| `GetStock` | unary | service | Доступный остаток по `product_id`. |
| `ReserveStock` | unary | service | Резерв позиций под `order_id`, атомарно: либо все позиции, либо ни одной. Нехватка → `FAILED_PRECONDITION` + `PreconditionFailure` (по каким товарам). Повтор с тем же `order_id` идемпотентен. **Искусственная задержка**: env `STOCK_RESERVE_DELAY_MS` (по умолчанию 0) и metadata `x-debug-delay-ms` — для уроков про deadline и ретраи. |
| `ReleaseStock` | unary | service | Снятие резерва по `order_id`, идемпотентно. |

Сиды: 20–30 товаров продавца-сида в 3–4 категориях, с остатками.

### 6.3. catalog.v2 — `CatalogService`

Новая версия контракта, как бывает при миграции:
- в v1 у `Product` цена — `int64 price_kopecks`;
- в v2 — `common.v1.Money price` под **другим номером поля**, `price_kopecks` удалён без `reserved`;
- `SearchProducts` в v2 требует обязательный `region_id`.

v2 содержит только `GetProduct` и `SearchProducts`. Сервер обслуживает **обе версии** на одном порту. Это материал для уроков про обратную совместимость и `buf breaking`.

### 6.4. orders.v1 — `OrderService` (порт 50053)

| Метод | Тип | Auth | Поведение |
|---|---|---|---|
| `AddCartItem` / `RemoveCartItem` / `GetCart` | unary | user | Корзина в Redis `cart:{user_id}`. `GetCart` подтягивает актуальные цены и остатки из catalog-service. Товар не найден → `NOT_FOUND`. |
| `Checkout` | unary | user | Оформляет заказ из корзины: email покупателя через `UserService.GetMe` (best-effort, снимок в заказе для уведомлений; users недоступен — заказ оформляется без email) → `StockService.ReserveStock` с пробросом deadline и `x-request-id` → заказ `CREATED` → корзина очищается. Metadata `idempotency-key` **обязательна** (нет → `INVALID_ARGUMENT`); повтор с тем же ключом возвращает тот же заказ (Redis `idem:{user_id}:{key}`, TTL 24 ч). Пустая корзина → `FAILED_PRECONDITION`. Нет товара → `FAILED_PRECONDITION` с деталями от catalog. Catalog недоступен или не ответил в срок → `UNAVAILABLE`, заказ не создаётся. |
| `GetOrder` | unary | user | Заказ, история смен статуса с метками времени (`history`) и порядок шагов доставки (`delivery_steps`, без `CANCELLED`). Чужой заказ → `NOT_FOUND` (не раскрываем существование). |
| `ListOrders` | unary | user | Заказы текущего пользователя, новые первыми, пагинация, фильтр по статусу. |
| `CancelOrder` | unary | user | Можно до `HANDED_TO_COURIER`, иначе `FAILED_PRECONDITION`. Снимает резерв (`ReleaseStock`). |
| `TrackOrder` | server stream | user | Первым сообщением — текущий статус (событие до подписки не теряется), дальше — каждое изменение с `changed_at`. Закрывается после `DELIVERED` или `CANCELLED`, trailing metadata `x-items-count`. Изменения приходят через Redis pub/sub `orders.status.{order_id}`. |

Доставку имитирует фоновая задача order-service (`@worker`-задача или `asyncio`-таск внутри сервиса):

```
CREATED → PAID → ASSEMBLING → HANDED_TO_COURIER → DELIVERED
```

Шаг — env `FULFILLMENT_STEP_MS`, по умолчанию 2000. Каждая смена статуса (включая `CREATED` из `Checkout` и `CANCELLED` из `CancelOrder`) пишется в Postgres вместе со строкой истории, публикуется в Redis (для `TrackOrder`) и событием `order.status_changed` в RabbitMQ (best-effort: брокер недоступен — статус всё равно сменён).

### 6.5. support.v1 — `SupportService` (порт 50054)

| Метод | Тип | Auth | Поведение |
|---|---|---|---|
| `Chat` | bidi | user | Чат по заказу. Входящие сообщения (`oneof`): `join{order_id}` — обязательно первым, иначе `FAILED_PRECONDITION`; `message{client_message_id, text}`; `read{message_id}`. Исходящие события (`oneof`): `joined{chat_id, last_messages}`, `ack{client_message_id, message_id, created_at}`, `message{message_id, author: AGENT/BOT, text, created_at}`, `agent_typing`. Подробности ниже. |
| `GetChatHistory` | unary | user | История чата по `order_id`, пагинация. |
| `GetOrderTimeline` | unary | service | Проекция статусов заказа из событий `order.status_changed` (`support.order_events`), старые первыми. Eventual consistency: отдаёт то, что успело дойти. В order-service не ходит. |

Поведение `Chat`:
- Заказ проверяется через `OrdersClient.GetOrder` с пробросом **пользовательского `authorization`** и `x-request-id`. Чужой или несуществующий заказ → стрим завершается `NOT_FOUND`.
- На каждое `message` сервер сразу шлёт `ack`. Сообщения сохраняются в Postgres.
- **Сервер пишет сам, не дожидаясь клиента:** через `SUPPORT_AGENT_DELAY_MS` (по умолчанию 1500) после `join` приходят `agent_typing` и сообщение `AGENT` «Здравствуйте, я оператор поддержки…». Тест не может читать ответы строго «запрос → ответ», и это учебная цель.
- Бот: если в тексте есть «статус» или «где», бот запрашивает у order-service актуальный статус и отвечает `BOT`-сообщением. Если order-service недоступен, бот отвечает «Не удалось получить статус, попробуйте позже», и **стрим не рвётся**.
- Через `SUPPORT_IDLE_TIMEOUT_S` (по умолчанию 60) без сообщений клиента сервер завершает стрим со статусом `OK` и trailing metadata `x-close-reason: idle`.
- RabbitMQ support-service не обязателен: без брокера сервис стартует, `Chat` и `GetChatHistory` работают, консьюмер проекции переподключается в фоне.

### 6.6. gateway (порт 8080)

BFF на FastAPI с интеграцией nuke-di (`nuke_di.fastapi.setup`). gRPC-клиенты к сервисам — nuke-di `Client`; gateway сам подставляет `x-api-key` и пробрасывает `authorization`.

Эндпоинты:
- `POST /auth/sign-up`, `POST /auth/confirm`, `POST /auth/sign-in`, `GET /me`;
- `GET /products`, `GET /products/{id}`;
- `GET /cart`, `POST /cart/items`, `DELETE /cart/items/{product_id}`;
- `POST /checkout` (заголовок `Idempotency-Key`), `GET /orders`, `GET /orders/{id}`.

Ошибки gRPC маппятся в HTTP-коды. Стримов на gateway нет: они живут между сервисами и в мобильных клиентах.

---

## 7. Docker и compose

- **Один Dockerfile** (`python:${PYTHON_VERSION}-slim` + uv, `ARG PYTHON_VERSION=3.12`, задаётся из `.env`) для всех Python-сервисов. Сервис выбирается командой (`python -m catalog_service.main` и т.п.). Многостадийная сборка, без dev-зависимостей в рантайме.
- Postgres, Redis и RabbitMQ — `*-alpine` (RabbitMQ без management-плагина), Mailpit — `axllent/mailpit`.
- У каждого контейнера:
  - `healthcheck`, у gRPC-сервисов — через стандартный health service: маленький Python-скрипт в образе, без отдельных бинарей;
  - `mem_limit`, ориентир: Python-сервис 128m, gateway 128m, frontend (nginx) 128m, Postgres 256m, Redis 64m, RabbitMQ 256m, Mailpit 64m (подбери по факту; бюджет ≤ ~1 ГБ — по фактическому потреблению `make stats`, не по сумме лимитов);
  - `restart: unless-stopped`.
- `depends_on` с `condition: service_healthy`. `make up` = `docker compose up -d --wait`.
- Compose profiles зарезервированы под будущие тяжёлые компоненты: по умолчанию вне базового набора ничего не стартует.
- `.env.example` содержит все переменные с дефолтами: порты, `STAND_API_KEY`, DSN, адреса соседей, задержки, шаг доставки, таймауты чата, TTL, лимит импорта, `SEED_SELLER_PASSWORD`, `SHUTDOWN_GRACE_SECONDS`, `CONNECT_TIMEOUT_SECONDS`.

---

## 8. Makefile

| Цель | Что делает |
|---|---|
| `install` | `uv sync --all-packages --all-groups` |
| `gen` | `grpc_tools.protoc` для всех `protos/**` → `pb/` с `--python_out --pyi_out --grpc_python_out` + стабы `mypy-protobuf` |
| `format` | `ruff format` + `ruff check --fix` |
| `lint` | `ruff check` |
| `typecheck` | `mypy` (strict, плагин nuke-di, `pb/` исключён) |
| `check` | `lint` + `typecheck` |
| `test` | тесты сервисов (раздел 9) |
| `up` / `down` | `docker compose up -d --wait` / `docker compose down -v` |
| `logs` / `ps` | логи и статус |
| `stats` | `docker stats --no-stream` (проверка бюджета памяти) |
| `reset` | `down` + `up` (чистые данные) |

---

## 9. Собственные тесты стенда

Это не тесты курса, а минимальная гарантия, что стенд работает:
- юнит-тесты хэндлеров с подменой клиентов через `DI.override` / `mock` ([Testing guide](https://github.com/troyan-dy/nuke-di/blob/master/docs/guide/testing.md));
- тест wiring'а nuke-di: дерево клиентов каждого сервиса собирается;
- тесты декоратора `rpc` и сервера:
  - неверная сигнатура (`request`/`context` не первые, нет type hints) падает при импорте;
  - расхождение с proto-дескриптором (тип стрима, классы сообщений, несуществующий метод) падает до старта;
  - доменные исключения дают нужные статус и details;
  - `x-request-id` и `x-items-count` выставляются;
- smoke-сценарий против поднятого стенда (маркер `stand`):
  1. `SignUp` → письмо с кодом в Mailpit (REST API, поллинг) → `ConfirmEmail` → `SignIn`;
  2. `SearchProducts` → `AddCartItem` → `Checkout` с `idempotency-key`;
  3. `TrackOrder` до `DELIVERED`;
  4. `Chat`: `join` → приветствие оператора → вопрос «где заказ» → ответ бота со статусом;
  5. заказ до `DELIVERED` поллингом `GetOrder` → письмо «Заказ доставлен» в `ListNotifications` и все пять статусов в `GetOrderTimeline` (одно событие — оба потребителя);
  6. продавцом: `ImportProducts` с одной заведомо плохой строкой → отчёт с ошибкой → `ExportProducts` содержит импортированные товары.

---

## 10. Definition of Done

- [ ] `make install && make gen && make check` — зелёные; mypy strict без `type: ignore` вне `pb/` (исключения обоснованы в `docs/decisions.md`).
- [ ] `make check && make test` проходят на Python 3.12 и 3.14 (`uv run --python 3.12 ...` / `--python 3.14`); стенд собирается с `PYTHON_VERSION=3.12` и `3.14`.
- [ ] `make up` на чистой машине поднимает стенд, все контейнеры `healthy`.
- [ ] `grpcurl -plaintext localhost:<port> list` показывает сервисы через reflection на 50051–50055, включая `catalog.v1` и `catalog.v2`.
- [ ] Все методы из раздела 6 работают как описано: статус-коды, rich details, `x-request-id`, `x-items-count`, идемпотентность `Checkout`, задержка `ReserveStock`, имитация доставки, независимые сообщения сервера в `Chat`.
- [ ] Вызов без `x-api-key` → `UNAUTHENTICATED`; метод продавца покупателем → `PERMISSION_DENIED`.
- [ ] Остановлен catalog-service → `Checkout` отдаёт `UNAVAILABLE`, а не висит. Остановлен order-service → `Chat` продолжает работать, бот сообщает о недоступности.
- [ ] `order.status_changed` доходит до обоих потребителей: `rabbitmqctl list_bindings` показывает две очереди на этот routing key; остановлен notification-service → заказ доезжает, проекция саппорта пополняется, очередь писем копится и дренится после старта (docs/stand/order-events-demo.md).
- [ ] `make test` зелёный, smoke-сценарий проходит против поднятого стенда.
- [ ] `make stats` — суммарно ≤ ~1 ГБ, цифры в README.
- [ ] README: запуск за 3 команды, таблица портов, схема из раздела 3, как добавить новый сервис.
- [ ] `docs/api.md` и `docs/decisions.md` заполнены.

## 11. Вне рамок

Брокеры сообщений сверх RabbitMQ, отправка писем наружу (письма остаются в Mailpit), платёжные провайдеры (оплата имитируется сменой статуса), TLS/mTLS, gRPC-Web/Envoy, метрики и трейсинг, Kubernetes, фронтенд сверх веб-интерфейса покупателя (`frontend/`, docs/decisions.md §27), фреймворк автотестов курса.

## 12. Порядок работы

1. Каркас workspace, Makefile, ruff, mypy, Dockerfile, compose с Postgres и Redis.
2. `stand_core`: Settings, Postgres, Redis, логирование, ошибки, декоратор `rpc`, `grpc_server`, интерцепторы, базовый gRPC-клиент к соседям, тесты.
3. catalog-service: `CatalogService` v1 и v2, `StockService`. На нём обкатать `rpc` и `grpc_server`, включая client- и server-stream.
4. user-service.
5. order-service: корзина, `Checkout` со `StockClient`, имитация доставки, `TrackOrder`.
6. support-service: `Chat` с `OrdersClient`.
7. gateway.
8. Smoke-сценарий, замер памяти, README и docs.

После каждого шага — `make check && make test`, коммит с понятным сообщением.

## 13. Ссылки

- nuke-di: https://github.com/troyan-dy/nuke-di — README, `docs/guide/clients.md`, `docs/guide/container.md`, `docs/guide/workers-and-jobs.md`, `docs/guide/servers-in-workers.md` (раздел grpc.aio), `docs/guide/testing.md`, `docs/guide/fastapi.md`, `llms.txt`
- grpcio-status (rich error model), grpcio-reflection, grpcio-health-checking — документация grpc.io для Python
- Образец декоратора `rpc` и сервера — `nuke/applications/grpc.py` внутреннего фреймворка Nuke; его API полностью перенесён в раздел 5, сам файл не нужен
