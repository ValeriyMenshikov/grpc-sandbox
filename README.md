# grpc-stand

Учебный стенд для курса «gRPC API Test Automation (Python)»: упрощённый бэкенд маркетплейса из пяти gRPC-сервисов и REST-шлюза. Поднимается одной командой в docker compose вместе с Postgres, Redis, RabbitMQ и Mailpit. Все четыре типа вызовов gRPC, rich error model, авторизация по metadata, deadline, идемпотентность, стримы; письмо с кодом подтверждения идёт через очередь в локальный почтовый ящик.

- Требования и поведение — [docs/stand/grpc-stand-TZ.md](docs/stand/grpc-stand-TZ.md)
- Методы, статус-коды, metadata — [docs/api.md](docs/api.md)
- Решения, принятые при реализации — [docs/decisions.md](docs/decisions.md)

## Запуск

Нужны Docker с compose v2, [uv](https://docs.astral.sh/uv/) и make.

```bash
cp .env.example .env   # необязательно: без .env compose берёт те же значения по умолчанию
make up                # собрать образ и поднять стенд, дождаться healthy
make smoke             # (нужен make install) прогнать smoke-сценарий против стенда
```

Проверить, что сервисы видны через reflection:

```bash
grpcurl -plaintext localhost:50052 list
# catalog.v1.CatalogService
# catalog.v1.StockService
# catalog.v2.CatalogService
# grpc.health.v1.Health
# grpc.reflection.v1alpha.ServerReflection

grpcurl -plaintext -H 'x-api-key: stand-secret-key' \
  -d '{"category": "books", "pagination": {"page_size": 3}}' \
  localhost:50052 catalog.v1.CatalogService/SearchProducts
```

`make smoke` берёт адреса только из окружения процесса, `.env` он не читает: по умолчанию хост `localhost` (`STAND_HOST`) и порты из `.env.example`. Если порты в `.env` изменены, экспортируйте его перед запуском — `set -a; . ./.env; set +a; make smoke`. Код подтверждения smoke берёт из письма через REST API Mailpit — `http://$STAND_HOST:$MAILPIT_UI_PORT/mail/api/v1`, переопределяется целиком через `SMOKE_MAILPIT_API_URL`; перед сценарием ящик очищается.

Остановить и удалить данные — `make down`, пересоздать с чистыми данными — `make reset`.

## Компоненты и порты

| Компонент | Порт (хост) | Протокол | За что отвечает |
|---|---|---|---|
| frontend | 3000 | HTTP (nginx) | Веб-интерфейс покупателя (Vue 3), прокси `/api` → gateway |
| gateway | 8080 | REST (FastAPI) → gRPC | BFF для веб-фронта |
| user-service | 50051 | gRPC | Регистрация, подтверждение email, вход, профиль |
| catalog-service | 50052 | gRPC | Каталог и поиск (v1 и v2); импорт/экспорт товаров продавца; остатки и резервы (`StockService`) |
| order-service | 50053 | gRPC | Корзина, оформление заказа, заказы, отслеживание доставки |
| support-service | 50054 | gRPC | Чат покупателя с поддержкой по заказу |
| notification-service | 50055 | gRPC + consumer | Забирает события из RabbitMQ, шлёт письма по SMTP в Mailpit, журнал попыток (`ListNotifications`) |
| postgres | 5432 | SQL | Одна БД `stand` (`stand`/`stand`), схема на сервис: `users`, `catalog`, `orders`, `support`, `notifications` |
| redis | 6379 | RESP | Коды подтверждения (user-service); сессии `session:{token}` читают все gRPC-сервисы (AuthInterceptor); корзины, ключи идемпотентности, pub/sub статусов заказов (order-service) |
| rabbitmq | 5672 | AMQP | Шина событий: topic exchange `stand.events` (`stand`/`stand`), очередь писем `notifications.email` и dead-letter `notifications.email.dead`; без management-плагина |
| mailpit | 1025 / 8025 | SMTP / HTTP | Локальный почтовый сервер: наружу не шлёт, письма видны в веб-ящике `/mail/` и в REST API `/mail/api/v1` |

Порты, ключи и задержки задаются в `.env` (см. `.env.example`). Ключ сервиса-клиента `x-api-key` — `stand-secret-key`; продавец-сид — `seller@stand.local` / `seller-password`.

Письма стенда (код подтверждения после регистрации) смотреть в веб-ящике Mailpit: через фронт — `http://localhost:3000/mail/`, напрямую — `http://localhost:${MAILPIT_UI_PORT:-8025}/mail/`. REST API ящика — `/mail/api/v1/...` (например, `GET /mail/api/v1/search?query=to:<email>`), им пользуются smoke и автотесты.

## Архитектура

```
Браузер ──HTTP──> frontend (nginx) ──/api──> gateway (BFF) ──gRPC──> user-service ──────────> Postgres, Redis
                                                           ├─gRPC──> catalog-service ─────────> Postgres, Redis
                                                           └─gRPC──> order-service ──gRPC──> catalog-service (StockService)
                                                                          └──> Postgres, Redis
               приложение поддержки ──gRPC──> support-service ──gRPC──> order-service
                                                    └──> Postgres, Redis
frontend (nginx) ──/mail──> Mailpit (веб-ящик + REST API)
user-service ──publish──> RabbitMQ (stand.events) ──> notification-service ──SMTP──> Mailpit
                                                             └──> Postgres (журнал писем)
Автотесты курса ──gRPC──> любой сервис;  ──SQL/Redis──> проверки состояния;  ──HTTP──> Mailpit API (письма)
```

| Тип | Метод | Зачем |
|---|---|---|
| unary | почти все методы | обычные запрос-ответ |
| client stream | `catalog.v1.CatalogService/ImportProducts` | продавец загружает фид, в ответ — отчёт об импорте |
| server stream | `catalog.v1.CatalogService/ExportProducts` | продавец выгружает каталог без пагинации |
| server stream | `orders.v1.OrderService/TrackOrder` | статус доставки в реальном времени (Redis pub/sub) |
| bidi | `support.v1.SupportService/Chat` | чат: клиент и поддержка пишут независимо |

## Структура

```
protos/            контракты: common/v1, users/v1, catalog/v1, catalog/v2, orders/v1, support/v1,
                   notifications/v1
pb/                сгенерированный код (make gen), в git
packages/core/     общая библиотека stand_core: Settings, логи, ошибки, декоратор rpc,
                   grpc_server, интерцепторы, клиенты Postgres/Redis/RabbitMQ, события (events),
                   базовый gRPC-клиент
services/<name>/   gRPC-сервисы: users, catalog, orders, support, notifications —
                   src/<name>_service/{settings,models,repository + schema.sql,convert,auth,
                   handlers/<method>_<in>_<out>.py,main}.py
services/gateway/  REST-фасад: src/gateway/{routers/<группа>.py,api,params,clients,
                   schemas,errors,context,main}.py
frontend/          веб-интерфейс покупателя: Vue 3 + Vite, src/{api,composables,components,pages},
                   nginx/default.conf.template, Dockerfile (node → nginx)
tests/             тесты контрактов и smoke-сценарий (маркер stand)
docker/Dockerfile  один образ для всех Python-сервисов
```

## Зависимости: nuke-di

Всё, что живёт дольше одного вызова (настройки, пул Postgres, Redis, репозитории, клиенты к соседям,
интерцепторы), — это *клиент*: подкласс `nuke_di.Client`. Зависимости клиента объявляются полями
dataclass через `@client_dataclass`, а не в `__init__` (имя поля для DI не важно, он смотрит на тип,
поэтому поля приватные); контейнер `DI` создаёт каждого ровно раз,
разбирает дерево по аннотациям и вызывает `connect()`/`disconnect()` в правильном порядке:

```python
@client_dataclass
class OrderRepository(Client):
    _postgres: Postgres  # зависимость: DI подставит единственный Postgres

    async def connect(self) -> None:  # после connect() самого Postgres
        await self._postgres.apply_schema(SCHEMA_PATH)
```

Внутреннее состояние (пул, канал, открытые стримы) — поле с `init=False`, его заполняет `connect()`:

```python
@client_dataclass
class Postgres(Client):
    _settings: Settings
    _pool: asyncpg.Pool | None = field(default=None, init=False)
```

Исключение одно: `Settings` и его подклассы — pydantic-модели, у них свой `__init__(self) -> None`
(иначе плагин nuke-di принял бы поля настроек за зависимости, docs/decisions.md §7).

Хэндлеры и эндпоинты получают клиентов так же — по аннотации аргумента; `main.py` сервиса делает
`inject_handlers(GRPC_HANDLERS)`, gateway — `nuke_di.fastapi.setup(app)`. В тестах клиент подменяется
на фейк через `DI.override(OrderRepository, fake)`.

## gateway: REST → gRPC

`gateway` — не gRPC-сервис, а BFF для фронта: каждый эндпоинт — один вызов соседа и перевод ответа
в JSON.

- `routers/<группа>.py` — эндпоинты одной группы (`health`, `users`, `catalog`, `cart`, `orders`),
  один `ClientRouter` на файл, имя группы = tag в OpenAPI (`/docs`)
- `routers/__init__.py` — `ROUTERS`, список роутеров в порядке групп; `api.py` включает их в
  корневой роутер, его берёт `main.py`
- `params.py` — общие query-параметры (`page_size`, `page_token`) и границы int32/int64
- `clients.py` — `UsersClient`, `CatalogClient`, `OrdersClient` на базовом `GrpcClient`
- `schemas.py` — pydantic-модели ответов (не `MessageToDict`), `errors.py` — gRPC-код → HTTP-код,
  `context.py` — ASGI-middleware, кладущий `authorization` и `x-request-id` в contextvars

Новый эндпоинт: функция в нужном `routers/<группа>.py` (новая группа — новый модуль и строка в
`ROUTERS`), вызов соседа — методом клиента из `clients.py`, ответ — модель из `schemas.py`.

## Команды

| Цель | Что делает |
|---|---|
| `make install` | `uv sync` всех пакетов workspace |
| `make gen` | `protos/**` → `pb/` (protoc + mypy-protobuf) |
| `make format` / `make lint` | ruff format + fix / проверка |
| `make typecheck` | mypy strict |
| `make check` | lint + typecheck |
| `make test` | тесты stand_core и сервисов, без smoke |
| `make cov` | тесты с покрытием (порог 80%) |
| `make smoke` | smoke-сценарий против поднятого стенда |
| `make front-install` | `npm ci` фронтенда |
| `make front-lint` / `make front-test` | ESLint + vue-tsc / Vitest фронтенда (в `check`/`test` не входят) |
| `make up` / `make down` | поднять (с пересборкой образа, `--wait`) / остановить и удалить данные |
| `make reset` | `down` + `up` |
| `make logs` / `make ps` / `make stats` | логи, статус, память контейнеров |

Другая версия Python: `UV_PROJECT_ENVIRONMENT=/tmp/stand-venv-314 PYTHON=3.14.2 make install check test` — отдельный venv, `.venv` на 3.12 не трогается; нужен обычный CPython, а не free-threaded `3.14t` (под него нет колёс grpcio-tools). Образ — `PYTHON_VERSION=3.14 make up` (поддерживаются 3.12 и 3.14).

## Память (`make stats`)

Замер сразу после `make up` и smoke, Python 3.12:

| Контейнер | Факт | `mem_limit` |
|---|---|---|
| users | ~58 МБ | 128m |
| gateway | ~53 МБ | 128m |
| notifications | ~49 МБ | 128m |
| catalog | ~42 МБ | 128m |
| orders | ~42 МБ | 128m |
| support | ~42 МБ | 128m |
| postgres | ~69 МБ | 256m |
| rabbitmq | ~96 МБ | 256m |
| mailpit | ~23 МБ | 64m |
| redis | ~20 МБ | 64m |
| frontend | ~8 МБ | 128m |
| **Итого** | **~500 МБ** | **1536 МБ** |

Бюджет C3 (~1 ГБ в покое) меряется фактом `docker stats`, а не суммой `mem_limit`.

## Фронтенд

Веб-интерфейс покупателя в `frontend/`: Vue 3, TypeScript, Vite, Vue Router, без UI-библиотеки. Вход, регистрация и подтверждение email, каталог с поиском, фильтрами и пагинацией, карточка товара, корзина, оформление заказа, список заказов и страница заказа с прогрессом доставки.

- Адрес — `http://localhost:3000`, порт на хосте — `FRONTEND_PORT`. Сервис `frontend` поднимается вместе со стендом (`make up`).
- Прокси: браузер ходит только на origin фронта. nginx отдаёт SPA (глубокие ссылки вроде `/orders/<id>` получают `index.html`) и проксирует `/api/*` на `${GATEWAY_URL}/*` со срезанным префиксом (`/api/products` → `http://gateway:8080/products`), поэтому CORS не нужен. `/mail/*` проксируется на `${MAILPIT_URL}/mail/*` без срезания префикса (у Mailpit `MP_WEBROOT=/mail`), включая WebSocket живых обновлений ящика. Адрес gateway резолвится на каждый запрос: фронт стартует и остаётся `healthy` при остановленном gateway, а `/api` в это время отвечает 502/504, и UI показывает «сервис недоступен». Healthcheck — собственный `/healthz` nginx.
- Оформление — один файл `frontend/src/style.css`: CSS-переменные (цвета, радиусы, тени, фокус-кольцо) и блоки под шапку, формы, карточки каталога, таблицы, шаги доставки и состояния. Светлая и тёмная темы — через `prefers-color-scheme`, анимации выключаются при `prefers-reduced-motion`. Шрифты системные: стенд работает офлайн, внешних CDN нет. Классы в разметке — семантические (`.product-item`, `.order-progress`, `.badge-<status>`), utility-классов и UI-библиотеки нет.
- Вход: сид-продавец `seller@stand.local` / `seller-password` (он может пользоваться корзиной и оформлять заказы). Новый пользователь после регистрации получает письмо с кодом подтверждения: экран подтверждения ссылается на ящик стенда `/mail/` (открывается в новой вкладке).
- Для `make up` Node не нужен — образ фронта собирается в Docker. Для разработки и проверок с хоста (`make front-*`, `npm run dev`) нужен Node.js 22 с npm, как в образе `node:22-alpine`.
- Разработка с хоста: `npm ci --prefix frontend` (или `make front-install`), затем `cd frontend && npm run dev`. Vite dev-proxy отправляет `/api/*` на `http://localhost:${GATEWAY_PORT:-8080}` со срезанным префиксом, как nginx, поэтому стенд (хотя бы gateway и его соседи) должен быть поднят.
- Проверки: `make front-lint` (ESLint + vue-tsc) и `make front-test` (Vitest). В `make check` / `make test` они не входят.

## Как добавить новый сервис

Новый сервис = контракт `protos/<name>/v1` + папка `services/<name>` + блок в `docker-compose.yml`. Образ, настройки, клиенты, декоратор `rpc` и сборка сервера берутся из `stand_core`. Пример — `services/catalog`.

1. **Контракт.** `protos/<name>/v1/<name>.proto` с `package <name>.v1;`, стиль buf STANDARD (`<Method>Request`/`<Method>Response`, enum с префиксом и `*_UNSPECIFIED = 0`). У каждого метода в комментарии — `Auth: service|user|seller`. `make gen`. Добавьте сервис в `tests/contracts/test_protos.py`.
2. **Пакет.** `services/<name>/pyproject.toml` (как у catalog: зависимости `stand-core`, `stand-protos` из workspace, `packages = ["src/<name>_service"]`), добавьте `services/<name>/src` в `mypy_path` корневого `pyproject.toml` и пакет в `COV_PACKAGES` Makefile. `make install`.
3. **Настройки.** `settings.py`: `class <Name>Settings(Settings)` с полями сервиса и `def __init__(self) -> None` (см. docs/decisions.md §7).
4. **Хэндлеры.** `handlers/<method>_<in>_<out>.py`, по одному на файл, `u` — unary, `s` — stream (`get_order_u_u.py`, `track_order_u_s.py`, `chat_s_s.py`). Хэндлер — свободная async-функция, первые два аргумента `request` и `context`, дальше зависимости-клиенты по type hint:

   ```python
   @rpc("GetThing", package="<name>.v1", service="<Name>Service")
   async def get_thing(
       request: thing_pb2.GetThingRequest,
       context: Context,
       repository: ThingRepository,
   ) -> thing_pb2.GetThingResponse: ...
   ```

   Ошибки — доменные исключения из `stand_core.grpc` (`InvalidArgument`, `NotFound`, `FailedPrecondition`, ...): статус и details выставит интерцептор. `handlers/__init__.py` импортирует все модули хэндлеров.
5. **Авторизация.** `auth.py` с `AUTH_POLICIES: dict[str, AuthPolicy]` на каждый метод (`"/<name>.v1.<Name>Service/GetThing": AuthPolicy.USER`). Метод без строки требует пользователя.
6. **Клиенты.** Postgres/Redis — `stand_core.clients`; репозиторий — `@client_dataclass` + `Client` с полем `_postgres: Postgres` и своим `schema.sql` (схема `<name>`), который применяется в `connect()`. Сосед — подкласс `GrpcClient` с `address_env = "<NEIGHBOUR>_ADDR"` и `dependency = "<neighbour>"`. Подробнее — раздел «Зависимости: nuke-di».
7. **`main.py`** — копия `services/catalog/src/catalog_service/main.py` с заменой имён.
8. **compose.** Блок с `<<: *python-service`, `command: ["python", "-m", "<name>_service.main"]`, `environment` (`<<: *common-env`, `GRPC_PORT`), `ports`, `depends_on` с `condition: service_healthy`, `healthcheck: *grpc-healthcheck`. Новые переменные — в `.env.example`. Не забудьте про бюджет памяти (`make stats`).
9. **Тесты.** `services/<name>/tests/`: хэндлеры напрямую с фейками, `test_server.py` in-process со всеми интерцепторами, `test_wiring.py`. `make check && make test`.
